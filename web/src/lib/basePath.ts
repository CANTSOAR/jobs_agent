// Plain string asset paths (<img src="/foo.svg">) aren't rewritten by Next's basePath
// handling the way next/image or next/link are -- prefix them with this explicitly so
// they resolve correctly under the GitHub Pages /jobs_agent subpath in production.
export const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
