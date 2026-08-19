/** Natural Spanish date formatting for History rows (FA-017.1 §21):
 * "Hoy, 1:42 PM" / "Ayer" / a full date fallback -- never a raw ISO
 * timestamp shown to the user. */
export function formatHistoryDate(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const time = new Intl.DateTimeFormat("es", { hour: "numeric", minute: "2-digit" }).format(date);

  if (date.toDateString() === now.toDateString()) {
    return `Hoy, ${time}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return "Ayer";
  }

  return new Intl.DateTimeFormat("es", { day: "numeric", month: "long", year: "numeric" }).format(date);
}
