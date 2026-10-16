// Matches app/schemas/jana.py; all UUIDs are serialized as strings.
export interface JanaSource {
  id: string;
  title: string;
  url: string;
  excerpt: string;
}

export interface JanaAnswer {
  answer: string;
  sources: JanaSource[];
  grounded: boolean;
  escalation_suggested: boolean;
  mode: 'generated' | 'excerpts' | 'refusal';
}

export interface JanaArticle {
  id: string;
  title: string;
  content: string;
  source_title: string;
  source_url: string | null;
}

// Use the same Bearer token as /ai/ask; a normal <a> cannot attach it.
// A download does not mean Google has imported the event.
export async function downloadLeaveCalendar(apiBase: string, requestId: string, token: string): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/requests/${encodeURIComponent(requestId)}/calendar.ics`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(response.status === 409
      ? 'Экспорт доступен для одобренного отпуска с корректными датами.'
      : 'Не удалось скачать файл календаря.');
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `leave-${requestId}.ics`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
