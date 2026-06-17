'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [isWhitelisted, setIsWhitelisted] = useState(false);

  useEffect(() => {
    async function checkWhitelist() {
      const { data: { user } } = await supabase.auth.getUser();

      if (!user) {
        router.push('/');
        return;
      }

      const { data } = await supabase
        .from('whitelisted_users')
        .select('email')
        .eq('email', user.email)
        .single();

      if (data) {
        setIsWhitelisted(true);
      }
      setLoading(false);
    }

    checkWhitelist();
  }, []);

  if (loading) {
    return <div className="flex-center" style={{ minHeight: '100vh' }}>Loading...</div>;
  }

  if (!isWhitelisted) {
    return (
      <div className="flex-center" style={{ minHeight: '100vh', flexDirection: 'column' }}>
        <h1 className="title">Access Denied</h1>
        <p className="subtitle" style={{ textAlign: 'center' }}>
          You are not currently on the whitelist.<br />
          Please email <a href="mailto:aryan.malik@rutgers.edu" style={{ color: 'var(--primary)' }}>aryan.malik@rutgers.edu</a> for agent access.
        </p>
        <button className="btn mt-4" onClick={() => supabase.auth.signOut().then(() => router.push('/'))}>Sign Out</button>
      </div>
    );
  }

  return (
    <div className="dashboard-layout">
      <aside className="sidebar">
        <h2 className="title" style={{ fontSize: '1.5rem', marginBottom: '0' }}>Agent Hub</h2>
        <nav className="sidebar-nav">
          <Link href="/dashboard" className="nav-item">Profile & Goals</Link>
          <Link href="/dashboard/companies" className="nav-item">Company Tracking</Link>
          <Link href="/dashboard/linkedin" className="nav-item">LinkedIn Tracking</Link>
          <Link href="/dashboard/matches" className="nav-item">Job Matches</Link>
        </nav>
      </aside>
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}
