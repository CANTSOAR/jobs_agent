'use client';

import Link from 'next/link';
import { useState } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { ApplicationStatus, isApplicationStatus } from '@/lib/applicationStatus';
import { ApplicationStatusBadge } from './ApplicationStatusBadge';

export interface ApplicationReference {
  id: string;
  job_id: string;
  status: ApplicationStatus;
}

interface JobApplicationActionProps {
  application?: ApplicationReference | null;
  jobId: string;
  targetUrl: string | null;
  userId: string | null;
  onQueued?: (application: ApplicationReference) => void;
}

export function JobApplicationAction({
  application,
  jobId,
  targetUrl,
  userId,
  onQueued,
}: JobApplicationActionProps) {
  const [queuedApplication, setQueuedApplication] = useState<ApplicationReference | null>(null);
  const [queueing, setQueueing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = queuedApplication || application || null;

  async function queueApplication() {
    if (!userId || queueing) return;

    setQueueing(true);
    setError(null);
    const { data, error: insertError } = await supabase
      .rpc('queue_application', { p_job_id: jobId, p_mode: 'autofill' });

    if (insertError) {
      // A second click or another tab may have won the unique (user_id, job_id)
      // race. In that case, recover by showing the already-created application.
      if (insertError.code === '23505') {
        const { data: existing, error: lookupError } = await supabase
          .from('applications')
          .select('id, job_id, status')
          .eq('user_id', userId)
          .eq('job_id', jobId)
          .single();

        if (existing && isApplicationStatus(existing.status)) {
          const reference = existing as ApplicationReference;
          setQueuedApplication(reference);
          onQueued?.(reference);
        } else {
          setError(lookupError?.message || 'This job is already in your application tracker.');
        }
      } else {
        setError(insertError.message);
      }
      setQueueing(false);
      return;
    }

    const queued = Array.isArray(data) ? data[0] : data;
    if (queued && isApplicationStatus(queued.status)) {
      const reference = queued as ApplicationReference;
      setQueuedApplication(reference);
      onQueued?.(reference);
    }
    setQueueing(false);
  }

  if (current) {
    return (
      <div className="job-application-action">
        <ApplicationStatusBadge status={current.status} />
        <Link href="/dashboard/applications" className="inline-link">
          View tracker
        </Link>
      </div>
    );
  }

  return (
    <div className="job-application-action">
      <button
        type="button"
        className="btn btn-compact"
        onClick={queueApplication}
        disabled={!userId || queueing || !targetUrl}
        title={!targetUrl ? 'This job does not have an application URL yet.' : undefined}
      >
        {queueing ? 'Queueing...' : 'Queue application'}
      </button>
      {error && <span className="inline-error" role="alert">{error}</span>}
    </div>
  );
}
