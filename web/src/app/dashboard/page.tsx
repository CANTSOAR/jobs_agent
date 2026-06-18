'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface RunRequest {
  id: string;
  status: string;
  request_type: string;
  requested_at: string;
}

export default function DashboardProfile() {
  const [userId, setUserId] = useState<string | null>(null);
  const [resumeText, setResumeText] = useState('');
  const [goalDescription, setGoalDescription] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingResume, setSavingResume] = useState(false);
  const [savingGoals, setSavingGoals] = useState(false);
  const [runRequests, setRunRequests] = useState<RunRequest[]>([]);
  const [requestingRun, setRequestingRun] = useState(false);
  const [requestingMatches, setRequestingMatches] = useState(false);
  const [emailNotifications, setEmailNotifications] = useState(true);

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setLoading(false);
        return;
      }
      setUserId(user.id);

      const [{ data }, { data: runs }] = await Promise.all([
        supabase.from('profiles').select('resume_text, goal_description, email_notifications_enabled').eq('id', user.id).single(),
        supabase.from('run_requests').select('id, status, request_type, requested_at').order('requested_at', { ascending: false }).limit(5),
      ]);

      if (data) {
        setResumeText(data.resume_text || '');
        setGoalDescription(data.goal_description || '');
        setEmailNotifications(data.email_notifications_enabled ?? true);
      }
      setRunRequests(runs || []);
      setLoading(false);
    })();
  }, []);

  async function toggleEmailNotifications() {
    if (!userId) return;
    const next = !emailNotifications;
    setEmailNotifications(next);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, email_notifications_enabled: next }, { onConflict: 'id' });
    if (error) {
      alert(error.message);
      setEmailNotifications(!next);
    }
  }

  async function refreshRunRequests() {
    const { data: runs } = await supabase
      .from('run_requests')
      .select('id, status, request_type, requested_at')
      .order('requested_at', { ascending: false })
      .limit(5);
    setRunRequests(runs || []);
  }

  async function requestRun() {
    if (!userId) return;
    setRequestingRun(true);
    const { error } = await supabase.from('run_requests').insert({ requested_by: userId, request_type: 'full' });
    if (error) alert(error.message);
    else await refreshRunRequests();
    setRequestingRun(false);
  }

  async function requestMatches() {
    if (!userId) return;
    setRequestingMatches(true);
    const { error } = await supabase.from('run_requests').insert({ requested_by: userId, request_type: 'evaluate_only' });
    if (error) alert(error.message);
    else await refreshRunRequests();
    setRequestingMatches(false);
  }

  async function saveResume() {
    if (!userId) return;
    setSavingResume(true);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, resume_text: resumeText }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingResume(false);
  }

  async function saveGoals() {
    if (!userId) return;
    setSavingGoals(true);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, goal_description: goalDescription }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingGoals(false);
  }

  if (loading) {
    return <p className="subtitle">Loading profile...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">Profile & Goals</h1>
      <p className="subtitle">Paste your resume and tell the agent what you&apos;re looking for.</p>

      <div className="card" style={{ marginBottom: '2.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: runRequests.length > 0 ? '1rem' : 0 }}>
          <div>
            <h2 style={{ marginBottom: '0.25rem' }}>Agent Control</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              The agent normally runs on whatever schedule you&apos;ve set up. Request an extra run any time.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', flexShrink: 0 }}>
            <button className="btn btn-secondary" onClick={requestMatches} disabled={requestingMatches}>
              {requestingMatches ? 'Requesting...' : 'Find My Matches Now'}
            </button>
            <button className="btn" onClick={requestRun} disabled={requestingRun}>
              {requestingRun ? 'Requesting...' : 'Run Agent Now'}
            </button>
          </div>
        </div>
        {runRequests.length > 0 && (
          <ul style={{ listStyle: 'none', display: 'grid', gap: '0.5rem', marginBottom: '1rem' }}>
            {runRequests.map(r => (
              <li key={r.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                <span>{new Date(r.requested_at).toLocaleString()} — {r.request_type === 'evaluate_only' ? 'find matches' : 'full run'}</span>
                <span className={`status-badge status-${r.status}`}>{r.status}</span>
              </li>
            ))}
          </ul>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
          <input type="checkbox" checked={emailNotifications} onChange={toggleEmailNotifications} />
          Email me when the agent finds a strong job match
        </label>
      </div>

      <div className="grid grid-cols-2">
        <div className="card">
          <h2 style={{ marginBottom: '1rem' }}>Resume</h2>
          <div className="input-group">
            <label>Paste your resume text</label>
            <textarea
              className="input-field textarea-field"
              placeholder="Paste your resume content here..."
              value={resumeText}
              onChange={e => setResumeText(e.target.value)}
            />
          </div>
          <button className="btn" onClick={saveResume} disabled={savingResume}>
            {savingResume ? 'Saving...' : 'Save Resume'}
          </button>
        </div>

        <div className="card">
          <h2 style={{ marginBottom: '1rem' }}>Career Goals</h2>
          <div className="input-group">
            <label>What exactly are you looking for?</label>
            <textarea
              className="input-field textarea-field"
              placeholder="e.g. Senior Frontend Engineer, remote, $150k+ base, Next.js focused..."
              value={goalDescription}
              onChange={e => setGoalDescription(e.target.value)}
            />
          </div>
          <button className="btn" onClick={saveGoals} disabled={savingGoals}>
            {savingGoals ? 'Saving...' : 'Save Goals'}
          </button>
        </div>
      </div>
    </div>
  );
}
