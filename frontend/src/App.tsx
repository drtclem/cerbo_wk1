import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router";

import { ApiError, apiGet } from "./api/client.ts";
import { BrandMark, BrandText, DEMO_DISCLAIMER } from "./components/Brand.tsx";
import { RoleSwitcher, type User } from "./components/RoleSwitcher.tsx";
import {
  STORAGE_KEY,
  demoLoginUserId,
  postDemoReset,
  storedUserId,
} from "./lib/demo.ts";
import { homeFor, navFor } from "./nav.ts";
import { AdminProductsPage } from "./pages/AdminProductsPage.tsx";
import { AuditRoute } from "./pages/AuditPage.tsx";
import { DashboardPage } from "./pages/DashboardPage.tsx";
import { NewOrderPage } from "./pages/NewOrderPage.tsx";
import { PatientOrderRoute } from "./pages/PatientOrderPage.tsx";
import { PatientOrdersPage } from "./pages/PatientOrdersPage.tsx";
import { ProductsPage } from "./pages/ProductsPage.tsx";

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

export default function App() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [me, setMe] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [booting, setBooting] = useState(true);
  const [authBusy, setAuthBusy] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    apiGet<User[]>("/users", null)
      .then((listed) => {
        if (cancelled) {
          return;
        }
        const id = storedUserId(listed, localStorage.getItem(STORAGE_KEY));
        setError(null);
        setUsers(listed);
        setUserId(id);
        setBooting(false);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(errorText(cause));
          setBooting(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (userId === null) {
      return;
    }
    let cancelled = false;
    apiGet<User>("/me", userId)
      .then((current) => {
        if (!cancelled) {
          setMe(current);
          setError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(errorText(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  function selectUser(nextId: number) {
    const next = users?.find((user) => user.id === nextId);
    const previous = users?.find((user) => user.id === userId);
    setError(null);
    setMe(null);
    setUserId(nextId);
    localStorage.setItem(STORAGE_KEY, String(nextId));
    const roleChanged = next !== undefined && previous !== undefined && next.role !== previous.role;
    if (roleChanged && !navFor(next.role).some((item) => item.to === location.pathname)) {
      navigate(homeFor(next.role));
    }
  }

  async function logIn() {
    if (authBusy) {
      return;
    }
    setAuthBusy(true);
    setError(null);
    try {
      await postDemoReset();
      const listed = await apiGet<User[]>("/users", null);
      const id = demoLoginUserId(listed);
      localStorage.setItem(STORAGE_KEY, String(id));
      setUsers(listed);
      setUserId(id);
      const provider = listed.find((user) => user.id === id);
      if (provider !== undefined) {
        navigate(homeFor(provider.role));
      }
    } catch (cause: unknown) {
      setError(errorText(cause));
    } finally {
      setAuthBusy(false);
    }
  }

  async function logOut() {
    if (authBusy) {
      return;
    }
    setAuthBusy(true);
    setError(null);
    try {
      await postDemoReset();
      localStorage.removeItem(STORAGE_KEY);
      setUserId(null);
      setMe(null);
      const listed = await apiGet<User[]>("/users", null);
      setUsers(listed);
      navigate("/");
    } catch (cause: unknown) {
      setError(errorText(cause));
    } finally {
      setAuthBusy(false);
    }
  }

  if (booting) {
    return (
      <div className="app-shell">
        <main className="app-main">
          <p>Loading…</p>
        </main>
      </div>
    );
  }

  if (userId === null) {
    return (
      <div className="app-shell">
        <header className="app-topbar">
          <Link to="/" className="app-brand">
            <BrandMark />
            <BrandText />
          </Link>
        </header>
        {error !== null ? (
          <p className="app-banner-error" role="alert">
            {error}
          </p>
        ) : null}
        <main className="app-main">
          <div className="login-screen">
            <BrandMark size={40} />
            <h1>Cerbo Supplements</h1>
            <p className="login-screen__note">
              This is a demo. Everything here is made up and resets when you log out.
            </p>
            <button type="button" disabled={authBusy} onClick={() => void logIn()}>
              Log in
            </button>
          </div>
        </main>
        <footer className="app-footer">{DEMO_DISCLAIMER}</footer>
      </div>
    );
  }

  const links = me === null ? [] : navFor(me.role);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <Link to="/" className="app-brand">
          <BrandMark />
          <BrandText />
        </Link>
        <nav className="app-nav" aria-label="Primary">
          {links.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="app-topbar__demo">
          {users !== null ? (
            <RoleSwitcher users={users} userId={userId} onChange={selectUser} />
          ) : null}
          <button
            type="button"
            className="secondary"
            disabled={authBusy}
            onClick={() => void logOut()}
          >
            Log out
          </button>
        </div>
      </header>
      {error !== null ? (
        <p className="app-banner-error" role="alert">
          {error}
        </p>
      ) : null}
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Home me={me} />} />
          <Route
            path="/products"
            element={me !== null ? <ProductsPage userId={me.id} /> : <p>Loading account…</p>}
          />
          <Route
            path="/orders/new"
            element={
              me !== null ? <NewOrderPage key={me.id} userId={me.id} /> : <p>Loading account…</p>
            }
          />
          <Route
            path="/dashboard"
            element={
              me !== null ? <DashboardPage key={me.id} userId={me.id} /> : <p>Loading account…</p>
            }
          />
          <Route
            path="/patient/orders"
            element={
              me !== null ? (
                <PatientOrdersPage key={me.id} userId={me.id} />
              ) : (
                <p>Loading account…</p>
              )
            }
          />
          <Route
            path="/orders/:orderId"
            element={
              me !== null && users !== null ? (
                <PatientOrderRoute key={me.id} userId={me.id} role={me.role} users={users} />
              ) : (
                <p>Loading account…</p>
              )
            }
          />
          <Route
            path="/orders/:orderId/audit"
            element={
              me !== null ? <AuditRoute key={me.id} userId={me.id} /> : <p>Loading account…</p>
            }
          />
          <Route
            path="/admin/products"
            element={
              me !== null ? (
                <AdminProductsPage key={me.id} userId={me.id} />
              ) : (
                <p>Loading account…</p>
              )
            }
          />
        </Routes>
      </main>
      <footer className="app-footer">{DEMO_DISCLAIMER}</footer>
    </div>
  );
}

function Home({ me }: { me: User | null }) {
  if (me === null) {
    return <p>Loading account…</p>;
  }
  return <Navigate to={homeFor(me.role)} replace />;
}
