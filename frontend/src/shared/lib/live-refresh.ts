/** Serial polling for visible screens; stops on unmount and resumes on focus. */
export function watchVisible(load: (signal: AbortSignal) => Promise<void>, interval = 1000) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  const run = async () => {
    if (running || controller.signal.aborted) return;
    clearTimeout(timer);
    if (document.visibilityState !== 'hidden') {
      running = true;
      try {
        await load(controller.signal);
      } catch {
        /* The next refresh retries transient failures. */
      } finally {
        running = false;
      }
    }
    if (!controller.signal.aborted) timer = setTimeout(run, interval);
  };
  const resume = () => {
    void run();
  };
  document.addEventListener('visibilitychange', resume);
  window.addEventListener('focus', resume);
  window.addEventListener('online', resume);
  void run();
  return () => {
    controller.abort();
    clearTimeout(timer);
    document.removeEventListener('visibilitychange', resume);
    window.removeEventListener('focus', resume);
    window.removeEventListener('online', resume);
  };
}
