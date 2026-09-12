'use client';

import { useEffect, useMemo, useState } from 'react';
import { ApplicationReference, JobApplicationAction } from '@/components/JobApplicationAction';
import { isApplicationStatus } from '@/lib/applicationStatus';
import { supabase } from '@/lib/supabaseClient';
import { basePath } from '@/lib/basePath';

interface Job {
  id: string;
  title: string;
  url: string | null;
  location: string | null;
  first_seen_at: string;
  posted_at: string | null;
  category: string | null;
  discovery_method: 'scrape' | 'feed' | 'mixed';
  companies: { name: string; favicon_url: string | null } | null;
}

const PAGE_SIZE = 200;

function fetchJobs(from: number) {
  return supabase
    .from('jobs')
    .select('id, title, url, location, first_seen_at, posted_at, category, discovery_method, companies(name, favicon_url)')
    .eq('is_active', true)
    .order('posted_at', { ascending: false, nullsFirst: false })
    .order('first_seen_at', { ascending: false })
    .range(from, from + PAGE_SIZE - 1);
}

export default function AllJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [companyFilter, setCompanyFilter] = useState('all');
  const [userId, setUserId] = useState<string | null>(null);
  const [applicationByJob, setApplicationByJob] = useState<Record<string, ApplicationReference>>({});
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setLoading(false);
        return;
      }
      setUserId(user.id);

      const [{ data: jobRows }, { data: applicationRows }] = await Promise.all([
        fetchJobs(0),
        supabase
          .from('applications')
          .select('id, job_id, status')
          .eq('user_id', user.id),
      ]);

      setJobs((jobRows as unknown as Job[]) || []);
      setHasMore((jobRows || []).length === PAGE_SIZE);
      const nextApplications: Record<string, ApplicationReference> = {};
      (applicationRows || []).forEach((application) => {
        if (isApplicationStatus(application.status)) {
          nextApplications[application.job_id] = application as ApplicationReference;
        }
      });
      setApplicationByJob(nextApplications);
      setLoading(false);
    })();
  }, []);

  function recordQueuedApplication(application: ApplicationReference) {
    setApplicationByJob((current) => ({ ...current, [application.job_id]: application }));
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const { data, error } = await fetchJobs(jobs.length);
    if (error) alert(error.message);
    else {
      const rows = (data as unknown as Job[]) || [];
      setJobs((current) => [...current, ...rows]);
      setHasMore(rows.length === PAGE_SIZE);
    }
    setLoadingMore(false);
  }

  const companyNames = useMemo(() => {
    const names = new Set(jobs.map(j => j.companies?.name).filter((n): n is string => Boolean(n)));
    return Array.from(names).sort();
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    const query = search.trim().toLowerCase();
    return jobs.filter(job => {
      if (companyFilter !== 'all' && job.companies?.name !== companyFilter) return false;
      if (!query) return true;
      return (
        job.title.toLowerCase().includes(query) ||
        (job.location || '').toLowerCase().includes(query) ||
        (job.companies?.name || '').toLowerCase().includes(query)
      );
    });
  }, [jobs, search, companyFilter]);

  if (loading) {
    return <p className="subtitle">Loading jobs...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">All Jobs</h1>
      <p className="subtitle">Recent open postings from the structured internship feed and tracked companies.</p>

      <div className="card" style={{ marginBottom: '2rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <div className="input-group" style={{ flex: 2, minWidth: '240px', marginBottom: 0 }}>
          <label>Search</label>
          <input
            className="input-field"
            placeholder="Title, company, or location..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="input-group" style={{ flex: 1, minWidth: '200px', marginBottom: 0 }}>
          <label>Company</label>
          <select className="input-field" value={companyFilter} onChange={e => setCompanyFilter(e.target.value)}>
            <option value="all">All companies</option>
            {companyNames.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
      </div>

      <p className="subtitle" style={{ fontSize: '0.9rem' }}>{filteredJobs.length} of {jobs.length} job(s)</p>

      <div className="grid">
        {filteredJobs.map(job => (
          <div key={job.id} className="card job-card">
            <img
              src={job.companies?.favicon_url || `${basePath}/file.svg`}
              alt=""
              className="company-favicon"
              onError={(e) => { (e.target as HTMLImageElement).src = `${basePath}/file.svg`; }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3 style={{ marginBottom: '0.25rem' }}>
                {job.url ? (
                  <a href={job.url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                    {job.title}
                  </a>
                ) : (
                  job.title
                )}
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                {job.companies?.name}{job.location ? ` — ${job.location}` : ''}
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: '0.3rem' }}>
                {job.category || 'Uncategorized'} · {job.discovery_method === 'scrape' ? 'company page' : 'structured feed'}
                {job.posted_at ? ` · posted ${new Date(job.posted_at).toLocaleDateString()}` : ''}
              </p>
            </div>
            <JobApplicationAction
              application={applicationByJob[job.id]}
              jobId={job.id}
              targetUrl={job.url}
              userId={userId}
              onQueued={recordQueuedApplication}
            />
          </div>
        ))}
        {filteredJobs.length === 0 && <p className="subtitle">No jobs match.</p>}
      </div>
      {hasMore && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '1.5rem' }}>
          <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? 'Loading...' : `Load ${PAGE_SIZE} more jobs`}
          </button>
        </div>
      )}
    </div>
  );
}
