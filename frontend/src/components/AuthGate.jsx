import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { getAuthStatus, logout } from '../api/client'

export default function AuthGate() {
  const location = useLocation()
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    let cancelled = false
    getAuthStatus()
      .then(() => {
        if (!cancelled) setStatus('authenticated')
      })
      .catch(() => {
        if (!cancelled) setStatus('unauthenticated')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogout() {
    await logout()
    setStatus('unauthenticated')
  }

  if (status === 'loading') {
    return <div className="p-8 text-sm text-slate-500">Wird geladen…</div>
  }

  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return (
    <>
      <button
        type="button"
        onClick={handleLogout}
        className="fixed right-4 top-4 z-30 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm hover:bg-slate-50"
      >
        Abmelden
      </button>
      <Outlet />
    </>
  )
}
