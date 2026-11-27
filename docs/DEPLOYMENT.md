# Deploying to AWS EC2 with docker-compose

One EC2 instance runs the whole stack (gateway, three services, Postgres, Redis, RabbitMQ, Prometheus,
Grafana) with Caddy in front for HTTPS. This is the simplest deployment that is still done properly:
TLS, no database ports on the internet, secrets outside git, backups. Its limits are listed at the end.

```
Internet --443--> [Caddy: TLS] --> [nginx gateway :8080] --> auth / wallet / notification services
                                                              |        |            |
                                                          Postgres   Redis      RabbitMQ      (all inside the Docker network,
                                                                                                 bound to 127.0.0.1 on the host)
Prometheus + Grafana: reached only through an SSH or SSM tunnel, never from the internet.
```

Caddy also fronts the web app: the API paths (`/auth`, `/wallets`, `/transfers`, `/admin`, `/notifications`, `/health`)
go to the gateway, every other path goes to the `frontend` container (the React app, built into the image by
`docker compose up --build`). See `deploy/Caddyfile`. The browser talks to a single HTTPS origin, so no CORS is needed.

## 1. What to create in AWS

| Thing | Setting | Why |
|---|---|---|
| AMI | Ubuntu Server 24.04 LTS | the scripts in `deploy/` target it |
| Instance type | **t3.large** (2 vCPU, 8 GB). t3.medium (4 GB) works for a demo | 10 containers; Postgres and RabbitMQ like memory |
| Storage | 30 GB gp3, **encrypted** | Docker images + Postgres data + Prometheus (7 days) |
| Metadata | IMDSv2 **required** (`HttpTokens=required`) | blocks SSRF-style theft of the instance role credentials |
| Elastic IP | allocate and attach | a stable address for DNS |
| DNS | an **A record** `api.example.com` -> the Elastic IP | Caddy needs it to get a certificate |
| IAM instance role | see section 3 | read secrets from SSM, no access keys on the box |

### Security group (the firewall): open as little as possible

| Direction | Port | Source | Why |
|---|---|---|---|
| Inbound | 443 / TCP | `0.0.0.0/0` and `::/0` | the API (HTTPS) |
| Inbound | 80 / TCP | `0.0.0.0/0` and `::/0` | Let's Encrypt certificate challenge and redirect to HTTPS |
| Inbound | 22 / TCP | **your IP only (`x.x.x.x/32`)**, or leave it out and use SSM Session Manager | admin access |
| Inbound | everything else | **nothing** | see below |
| Outbound | all (default) | `0.0.0.0/0` | image pulls, Let's Encrypt, SSM, S3 |

**Never open** 8080 (gateway), 8001-8003 (services), 5432 (Postgres), 6379 (Redis), 5672/15672 (RabbitMQ),
9090 (Prometheus), 3000 (Grafana). Defence in depth: `docker-compose.yml` already binds all of them to
`127.0.0.1`, so they are unreachable from outside even if a security-group rule is added by mistake. Caddy is
the only container that listens on a public address.

```bash
# CLI version of the table (default VPC; adjust to yours)
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --group-name wallet-platform --description wallet-platform \
          --vpc-id "$VPC_ID" --query GroupId --output text)
MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
  'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]' \
  'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]' \
  "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP}/32,Description=admin}]"
```

## 2. First login and install

```bash
ssh -i your-key.pem ubuntu@<elastic-ip>
git clone <your repository url> wallet-platform && cd wallet-platform
bash deploy/bootstrap_ec2.sh     # Docker Engine + Compose plugin, make, AWS CLI, 2 GB swap
exit                             # log back in so the `docker` group applies
```

## 3. Environment and secrets

The stack is configured entirely through **one `.env` file** that Docker Compose and the Makefile both read.
Rules:

- `.env` is **never committed** (it is in `.gitignore`), lives only on the server, and is `chmod 600`.
- Values must not contain `#`, `$`, quotes or spaces. Use **letters and digits only** for `POSTGRES_PASSWORD`
  and `RABBITMQ_DEFAULT_PASS`: they are placed inside connection URLs. `openssl rand -hex 32` is a safe generator.
- Secrets are not baked into images and not passed as command-line arguments.
- Do not paste the output of `docker compose config` anywhere: it prints every secret.

| Variable | Secret? | Production value |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | password: yes | `wallet`, `openssl rand -hex 24` |
| `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` | password: yes | `wallet`, `openssl rand -hex 24` |
| `JWT_SECRET` | **yes** | `openssl rand -hex 32` (64 chars; min. 32 is enforced). Changing it logs everyone out |
| `GRAFANA_ADMIN_PASSWORD` | yes | `openssl rand -hex 16` |
| `DOMAIN`, `ACME_EMAIL` | no | `api.example.com`, your email (certificate expiry notices) |
| `COMPOSE_FILE` | no | `docker-compose.yml:deploy/docker-compose.prod.yml` (makes every `docker compose` / `make` command use the production overrides) |
| `LOG_LEVEL`, `BCRYPT_ROUNDS`, rate-limit and fraud settings | no | defaults are fine (`INFO`, `12`) |

**Option A: write it by hand** (fine for one server):

```bash
cp .env.example .env && chmod 600 .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
sed -i "s/^RABBITMQ_DEFAULT_PASS=.*/RABBITMQ_DEFAULT_PASS=$(openssl rand -hex 24)/" .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
sed -i "s/^GRAFANA_ADMIN_PASSWORD=.*/GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)/" .env
cat >> .env <<'ENV'
DOMAIN=api.example.com
ACME_EMAIL=you@example.com
COMPOSE_FILE=docker-compose.yml:deploy/docker-compose.prod.yml
ENV
```

**Option B: AWS Systems Manager Parameter Store** (secrets live in AWS, encrypted with KMS, auditable):

```bash
# once, from your laptop or CloudShell: one SecureString per variable
for name in POSTGRES_PASSWORD RABBITMQ_DEFAULT_PASS JWT_SECRET GRAFANA_ADMIN_PASSWORD; do
  aws ssm put-parameter --name "/wallet-platform/prod/$name" --type SecureString \
      --value "$(openssl rand -hex 32)" --overwrite
done
aws ssm put-parameter --name /wallet-platform/prod/POSTGRES_USER --type String --value wallet
aws ssm put-parameter --name /wallet-platform/prod/RABBITMQ_DEFAULT_USER --type String --value wallet
aws ssm put-parameter --name /wallet-platform/prod/DOMAIN --type String --value api.example.com
aws ssm put-parameter --name /wallet-platform/prod/ACME_EMAIL --type String --value you@example.com
aws ssm put-parameter --name /wallet-platform/prod/COMPOSE_FILE --type String \
    --value docker-compose.yml:deploy/docker-compose.prod.yml

# on the server (the instance role grants read access; no keys are stored on the box)
bash deploy/render_env_from_ssm.sh      # writes .env with mode 600
```

Instance-role policy for Option B (attach to the role of the instance, together with the AWS-managed
`AmazonSSMManagedInstanceCore` if you want Session Manager). If you encrypt the parameters with your own KMS
key instead of the default `aws/ssm` key, also allow `kms:Decrypt` on that key.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"],
    "Resource": [
      "arn:aws:ssm:REGION:ACCOUNT_ID:parameter/wallet-platform/prod",
      "arn:aws:ssm:REGION:ACCOUNT_ID:parameter/wallet-platform/prod/*"
    ]
  }]
}
```

## 4. Start and verify

```bash
docker compose config -q                 # validates the files and the .env (prints nothing)
docker compose up -d --build --wait      # builds the images on the instance, runs migrations on start
docker compose ps                        # everything should be "healthy" / "running"
curl -i https://api.example.com/health   # {"status":"ok","service":"gateway"} with a valid certificate
make create-admin EMAIL=you@example.com # first admin (password prompt); registration only makes normal users
GATEWAY_URL=https://api.example.com make smoke   # end-to-end check, including request-id tracing
# The smoke test creates smoke-*@example.com users and an admin with a random one-off password, and
# deactivates them when it finishes. Prefer running it on staging; never run the load test on production.
```

If the certificate does not appear: the A record must already point at the Elastic IP and ports 80/443 must be
open; look at `docker compose logs caddy`. (Let's Encrypt rate-limits repeated failures: fix, then wait.)

## 5. Operating it

**Grafana and Prometheus** are not exposed. Use a tunnel, then open `http://localhost:3000`:

```bash
ssh -i your-key.pem -L 3000:localhost:3000 -L 9090:localhost:9090 ubuntu@<elastic-ip>
# or, without opening port 22 at all (needs the SSM plugin for the AWS CLI):
aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSession \
    --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

**Update / roll back** (migrations run on container start; they only move forward, so a rollback of code
across a migration needs a database restore or a compensating migration):

```bash
git pull && docker compose up -d --build --wait && make verify
git checkout <previous-tag> && docker compose up -d --build --wait     # rollback of code
```

**Logs**: `docker compose logs -f --tail=100 wallet-service`. Containers rotate logs (3 x 10 MB each). Follow one
request through every service with its id: `docker compose logs --no-color | grep <request-id>`.

**Backups**:

```bash
sudo mkdir -p /var/backups/wallet-platform && sudo chown ubuntu /var/backups/wallet-platform
S3_BUCKET=my-backup-bucket bash deploy/backup_postgres.sh          # try it once by hand
echo '15 2 * * * ubuntu cd /home/ubuntu/wallet-platform && S3_BUCKET=my-backup-bucket bash deploy/backup_postgres.sh >> /var/log/wallet-backup.log 2>&1' \
  | sudo tee /etc/cron.d/wallet-backup
# restore one database (stop the service that uses it first):
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d wallet_db --clean --if-exists < wallet_db-<stamp>.dump
```

Also schedule **EBS snapshots** (AWS Backup or Data Lifecycle Manager): they capture the volume, including
RabbitMQ and Redis state, at one point in time. **Test a restore** before you trust any backup.

**After any incident or load test**: `make verify` proves the ledger sums to zero, no user balance is negative, and every
transfer produced exactly one event and the right notifications.

## 6. Security checklist

- [ ] Security group: only 80/443 open to the world, 22 restricted to your IP (or no 22 + SSM)
- [ ] `curl http://<elastic-ip>:8080`, `:5432`, `:3000` from another machine all time out
- [ ] IMDSv2 required; EBS encrypted; instance role limited to the SSM prefix (and your backup bucket)
- [ ] `.env` is mode 600, absent from git (`git status`), and no secret appears in `docker compose logs`
- [ ] Grafana admin password changed from the example; Grafana/Prometheus reached only through a tunnel
- [ ] `unattended-upgrades` enabled (default on Ubuntu) and the instance rebooted for kernel updates
- [ ] Backups restore successfully, and the instance has a CloudWatch alarm for CPU and status checks

## 7. Limits of this deployment (and what to change next)

- **One host is a single point of failure.** There is no high availability and no autoscaling. Next steps: an ALB
  in front of two instances, with Postgres on **RDS**, Redis on **ElastiCache** and RabbitMQ on **Amazon MQ**
  (point `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL` at them and drop those containers).
- **ALB instead of Caddy**: terminate TLS with an ACM certificate on the load balancer and send traffic to the
  gateway; the security group of the instance then allows 8080 only from the ALB's security group. Keep the
  `realip.conf` idea (trust the ALB's `X-Forwarded-For`).
- Images are built on the instance. A stricter setup builds in CI, pushes to **ECR**, and pulls pinned tags.
- Dependencies are version ranges, so a rebuild may pick up newer releases. Pin exact versions (lockfile) before
  relying on reproducible builds.
- No alert rules yet: Grafana shows the numbers but nothing pages you.

## 8. Tear down

```bash
docker compose down -v        # also deletes the data volumes: this destroys the databases
```
Then terminate the instance, release the Elastic IP, and delete the security group, role and SSM parameters.
