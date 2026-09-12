'use client';

import { useEffect, useState } from 'react';
import { ApplicationReference, JobApplicationAction } from '@/components/JobApplicationAction';
import { isApplicationStatus } from '@/lib/applicationStatus';
import { supabase } from '@/lib/supabaseClient';
import { basePath } from '@/lib/basePath';

interface JobMatch {
  id: string;
  score: number;
  reasoning: string | null;
  status: string;
  created_at: string;
  jobs: {
    id: string;
    title: string;
    url: string | null;
    location: string | null;
    companies: { name: string; favicon_url: string | null } | null;
  } | null;
}

export default function JobMatches() {
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [userId, setUserId] = useState<string | null>(null);
  const [applicationByJob, setApplicationByJob] = useState<Record<string, ApplicationReference>>({});

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setLoading(false);
        return;
      }
      setUserId(user.id);

      const [{ data: matchRows }, { data: applicationRows }] = await Promise.all([
        supabase
          .from('user_job_matches')
          .select('id, score, reasoning, status, created_at, jobs(id, title, url, location, companies(name, favicon_url))')
          .order('score', { ascending: false }),
        supabase
          .from('applications')
          .select('id, job_id, status')
          .eq('user_id', user.id),
      ]);

      setMatches((matchRows as unknown as JobMatch[]) || []);
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

  if (loading) {
    return <p className="subtitle">Loading matches...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">Job Matches</h1>
      <p className="subtitle">Jobs the agent found at companies you track, scored against your resume and goals.</p>

      <div className="grid">
        {matches.map(match => {
          const job = match.jobs;
          const company = job?.companies;
          return (
            <div key={match.id} className="card match-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', minWidth: 0 }}>
                <img
                  src={company?.favicon_url || `${basePath}/file.svg`}
                  alt=""
                  className="company-favicon"
                  onError={(e) => { (e.target as HTMLImageElement).src = `${basePath}/file.svg`; }}
                />
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ marginBottom: '0.25rem' }}>
                    {job?.url ? (
                      <a href={job.url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {job?.title}
                      </a>
                    ) : (
                      job?.title
                    )}
                  </h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                    {company?.name}{job?.location ? ` — ${job.location}` : ''}
                  </p>
                  {match.reasoning && (
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.5rem' }}>{match.reasoning}</p>
                  )}
                </div>
              </div>
              <div className="match-actions">
                <span className="status-badge status-approved">{match.score}/100</span>
                {job && (
                  <JobApplicationAction
                    application={applicationByJob[job.id]}
                    jobId={job.id}
                    targetUrl={job.url}
                    userId={userId}
                    onQueued={recordQueuedApplication}
                  />
                )}
              </div>
            </div>
          );
        })}
        {matches.length === 0 && (
          <p className="subtitle">
            No matches yet — make sure you&apos;ve saved a resume/goals and subscribed to some companies.
          </p>
        )}
      </div>
    </div>
  );
}
