import { APPLICATION_STATUS_META, ApplicationStatus } from '@/lib/applicationStatus';

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  const meta = APPLICATION_STATUS_META[status];

  return (
    <span
      className="status-badge application-status-badge"
      data-tone={meta.tone}
      title={meta.description}
    >
      {meta.label}
    </span>
  );
}
