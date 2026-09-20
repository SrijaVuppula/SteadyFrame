// The API exposes no way to fetch the original input back, so the click-through preview of
// an upload made in this tab uses the File we still hold in memory. Lost on reload, by design.
const files = new Map<string, File>();

export const rememberUpload = (jobId: string, file: File) => files.set(jobId, file);
export const recallUpload = (jobId: string): File | undefined => files.get(jobId);
