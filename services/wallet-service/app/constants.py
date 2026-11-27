from uuid import UUID

# The counter-party of every deposit. Must match the row inserted by migration 001.
SYSTEM_WALLET_ID = UUID("00000000-0000-0000-0000-000000000001")
