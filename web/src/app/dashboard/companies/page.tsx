'use client';
import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface Company {
  id: string;
  name: string;
  careers_page_url: string;
  favicon_url: string | null;
  status: string;
  rejection_reason: string | null;
}

interface ActionablePost {
  id: string;
  post_url: string;
  post_text: string | null;
  agent_reasoning: string | null;
  first_seen_at: string;
  companies: { name: string; favicon_url: string | null } | null;
}

export default function CompaniesTracking() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [myRequests, setMyRequests] = useState<Company[]>([]);
  const [actionablePosts, setActionablePosts] = useState<ActionablePost[]>([]);
  const [subscribedIds, setSubscribedIds] = useState<Set<string>>(new Set());
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) {
      setLoading(false);
      return;
    }
    setUserId(user.id);

    const [{ data: approved }, { data: requests }, { data: subs }, { data: posts }] = await Promise.all([
      supabase.from('companies').select('*').eq('status', 'approved').order('name'),
      supabase.from('companies').select('*').eq('requested_by', user.id).neq('status', 'approved').order('created_at', { ascending: false }),
      supabase.from('user_company_subscriptions').select('company_id').eq('user_id', user.id),
      // RLS already restricts this to actionable posts from companies the user is subscribed to.
      supabase
        .from('company_linkedin_posts')
        .select('id, post_url, post_text, agent_reasoning, first_seen_at, companies(name, favicon_url)')
        .order('first_seen_at', { ascending: false }),
    ]);

    setCompanies(approved || []);
    setMyRequests(requests || []);
    setSubscribedIds(new Set((subs || []).map((s: { company_id: string }) => s.company_id)));
    setActionablePosts((posts as unknown as ActionablePost[]) || []);
    setLoading(false);
  }

  async function toggleSubscription(companyId: string) {
    if (!userId) return;
    const isSubscribed = subscribedIds.has(companyId);
    const next = new Set(subscribedIds);

    if (isSubscribed) {
      next.delete(companyId);
      setSubscribedIds(next);
      await supabase.from('user_company_subscriptions').delete().eq('user_id', userId).eq('company_id', companyId);
    } else {
      next.add(companyId);
      setSubscribedIds(next);
      await supabase.from('user_company_subscriptions').insert({ user_id: userId, company_id: companyId });
    }
  }

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSubmitting(true);

    const { error } = await supabase.from('companies').insert({
      name,
      careers_page_url: url,
      requested_by: userId,
      status: 'pending',
    });

    if (error) {
      alert(error.message);
    } else {
      setName('');
      setUrl('');
      await loadData();
    }
    setSubmitting(false);
  }

  if (loading) {
    return <p className="subtitle">Loading companies...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">Company Tracking</h1>
      <p className="subtitle">Check the companies you want the agent to monitor for new job postings.</p>

      <div className="grid grid-cols-3" style={{ marginBottom: '2.5rem' }}>
        {companies.map(company => (
          <label key={company.id} className="card company-card">
            <img
              src={company.favicon_url || '/file.svg'}
              alt=""
              className="company-favicon"
              onError={(e) => { (e.target as HTMLImageElement).src = '/file.svg'; }}
            />
            <div className="company-card-body">
              <h3>{company.name}</h3>
              <a href={company.careers_page_url} target="_blank" rel="noreferrer">View Page ↗</a>
            </div>
            <input
              type="checkbox"
              checked={subscribedIds.has(company.id)}
              onChange={() => toggleSubscription(company.id)}
            />
          </label>
        ))}
        {companies.length === 0 && <p className="subtitle">No approved companies yet — request one below.</p>}
      </div>

      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 style={{ marginBottom: '1rem' }}>Request a New Company</h2>
        <form onSubmit={handleRequest}>
          <div className="grid grid-cols-2">
            <div className="input-group">
              <label>Company name</label>
              <input className="input-field" value={name} onChange={e => setName(e.target.value)} required />
            </div>
            <div className="input-group">
              <label>Careers page URL</label>
              <input type="url" className="input-field" value={url} onChange={e => setUrl(e.target.value)} required />
            </div>
          </div>
          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Submitting...' : 'Request Company'}
          </button>
        </form>
        <p className="subtitle" style={{ fontSize: '0.85rem', marginTop: '1rem', marginBottom: 0 }}>
          The agent reviews new requests on its next scheduled run and approves it automatically if it looks like a real careers page.
        </p>
      </div>

      {myRequests.length > 0 && (
        <div style={{ marginBottom: '2.5rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Your Requests</h2>
          <div className="grid">
            {myRequests.map(company => (
              <div key={company.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h3 style={{ marginBottom: '0.25rem' }}>{company.name}</h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{company.careers_page_url}</p>
                  {company.status === 'rejected' && company.rejection_reason && (
                    <p style={{ color: 'var(--accent)', fontSize: '0.85rem' }}>{company.rejection_reason}</p>
                  )}
                </div>
                <span className={`status-badge status-${company.status}`}>{company.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {actionablePosts.length > 0 && (
        <div>
          <h2 style={{ marginBottom: '1rem' }}>Actionable LinkedIn Activity</h2>
          <p className="subtitle" style={{ fontSize: '0.9rem' }}>
            Posts from companies you track that the agent flagged as a real opportunity.
          </p>
          <div className="grid">
            {actionablePosts.map(post => (
              <a
                key={post.id}
                href={post.post_url}
                target="_blank"
                rel="noreferrer"
                className="card company-card"
                style={{ textDecoration: 'none', color: 'inherit', alignItems: 'flex-start' }}
              >
                <img
                  src={post.companies?.favicon_url || '/file.svg'}
                  alt=""
                  className="company-favicon"
                  onError={(e) => { (e.target as HTMLImageElement).src = '/file.svg'; }}
                />
                <div className="company-card-body">
                  <h3>{post.companies?.name}</h3>
                  {post.agent_reasoning && (
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>{post.agent_reasoning}</p>
                  )}
                  {post.post_text && <p style={{ fontSize: '0.85rem' }}>{post.post_text}</p>}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
