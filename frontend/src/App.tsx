import { useAuth } from "./auth/AuthContext";
import { AuthPage } from "./components/AuthPage";
import { Shell } from "./components/Shell";

export default function App() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <p className="splash" role="status">
        Loading…
      </p>
    );
  }
  return user ? <Shell user={user} /> : <AuthPage />;
}
