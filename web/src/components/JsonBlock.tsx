// Collapsible pretty-printed JSON. Native <details> keeps it keyboard-accessible for free.
export function JsonBlock({ label, value, open }: { label: string; value: unknown; open?: boolean }) {
  return (
    <details className="json-block" open={open}>
      <summary>{label}</summary>
      <pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
