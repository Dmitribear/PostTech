import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Avatar, ErrorState, Icon, LoadingState, Modal, PageHeader } from '../components/ui';
import { errorMessage } from '../lib/api';
import type { JanaAnswer, JanaArticle } from '../lib/types';
import './support.css';

type Message = { id: number; role: 'user'; text: string } | { id: number; role: 'jana'; result: JanaAnswer };
const prompts = [
  { text: 'Как оформить отпуск?', icon: 'plane' },
  { text: 'Как запросить аванс?', icon: 'wallet' },
  { text: 'Где посмотреть статус заявки?', icon: 'clipboard' },
  { text: 'Кто видит мои кадровые данные?', icon: 'shield' },
];
function safeSourceUrl(url: string | null): string | null {
  if (!url) return null;
  try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null; }
  catch { return null; }
}

export default function Jana() {
  const { api, profile, mode } = usePortal();
  const [source, setSource] = useState<JanaAnswer['sources'][number] | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const generation = useRef(0);
  const sending = useRef(false);
  const counter = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, busy]);
  async function ask(value: string) {
    const text = value.trim();
    if (sending.current) return;
    if (text.length < 3) { setError('Напишите вопрос длиной не менее трёх символов.'); return; }
    if (text.length > 2000) { setError('Сократите вопрос до 2000 символов.'); return; }
    const current = generation.current;
    const messageId = ++counter.current;
    sending.current = true; setBusy(true); setError(''); setQuestion('');
    setMessages(previous => [...previous, { id: messageId, role: 'user', text }]);
    try {
      const result = await api.askJana(text);
      if (current === generation.current) setMessages(previous => [...previous, { id: ++counter.current, role: 'jana', result }]);
    } catch (err) {
      if (current === generation.current) {
        setError(errorMessage(err)); setQuestion(text);
        setMessages(previous => previous.filter(message => message.id !== messageId));
      }
    } finally {
      sending.current = false;
      if (current === generation.current) { setBusy(false); composer.current?.focus(); }
    }
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(question); }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(question); }
  }
  return <div className="support-page">
    <PageHeader title="AI Jana" description="Ваш помощник по кадровым вопросам и внутренним правилам" eyebrow="Всегда рядом" />
    {mode === 'demo' && <p className="support-demo-note">{api.janaAvailable ? 'Jana ищет ответы локально в учебных материалах. Эти материалы — примеры, а не утверждённые правила JanaPost.' : 'В этой демоверсии локальная Jana не подключена. Для ответа нужен работающий сервер и база знаний.'}</p>}
    {source && <SourceDialog source={source} onClose={() => setSource(null)} />}
    <div className="support-chat-layout">
      <section className="card support-chat" aria-label="Чат с AI Jana">
        <div className="support-chat-top"><div className="support-chat-identity"><span className="support-jana-icon"><Icon name="bot" size={21} /></span><div><h2>Jana · HR-помощник</h2><p>{mode === 'demo' ? (api.janaAvailable ? 'Локальная модель · демонстрационная база' : 'Локальная Jana не подключена') : 'Локальная модель · ответы по базе знаний'}</p></div></div><button className="btn btn-ghost" disabled={busy || !messages.length} onClick={() => { generation.current += 1; setMessages([]); setError(''); setQuestion(''); composer.current?.focus(); }}><Icon name="plus" size={15} />Новый диалог</button></div>
        {!messages.length && !busy ? <div className="support-chat-welcome"><div className="support-jana-icon"><Icon name="sparkles" size={29} /></div><span className="support-eyebrow">Меньше поиска. Больше ясности.</span><h2 style={{ marginTop: 12 }}>С чего начнём?</h2><p>Я помогу разобраться с отпуском, авансом и правилами компании. Задайте вопрос своими словами или выберите тему.</p><div className="support-prompts">{prompts.map(prompt => <button className="support-prompt" key={prompt.text} disabled={!api.janaAvailable} onClick={() => void ask(prompt.text)}><Icon name={prompt.icon} size={19} />{prompt.text}</button>)}</div></div> : <div className="support-chat-messages" role="log" aria-label="Сообщения диалога" aria-live="polite" aria-relevant="additions text">
          {messages.map(message => <div key={message.id} className={`support-message ${message.role}`}>
            {message.role === 'user' ? <Avatar name={profile.full_name} size={29} /> : <span className="support-jana-icon"><Icon name="bot" size={18} /></span>}
            <div className="support-message-bubble"><span className="support-message-author">{message.role === 'user' ? 'Вы' : 'AI Jana'}</span>{message.role === 'user' ? message.text : <><p className="support-answer-text">{message.result.answer}</p>{message.result.sources.length > 0 && <div className="support-citations"><span className="support-citations-label">Источники ответа</span>{message.result.sources.map(source => <button type="button" className="support-citation" key={source.id} onClick={() => setSource(source)}><Icon name="file" size={12} />{source.title}<Icon name="arrow-right" size={11} /></button>)}</div>}{message.result.escalation_suggested && <span className="support-message-refusal">Для подтверждения информации обратитесь в ваш HR-отдел.</span>}</>}</div>
          </div>)}
          {busy && <div className="support-message"><span className="support-jana-icon"><Icon name="bot" size={18} /></span><span className="support-chat-typing" role="status">Ищу ответ в базе знаний…</span></div>}
          <div ref={end} />
        </div>}
        <form className="support-chat-composer" onSubmit={submit}>
          {error && <p className="support-inline-error" role="alert" style={{ marginBottom: 10 }}>{error}</p>}
          <div className="support-composer-box"><textarea ref={composer} value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={keyDown} placeholder="Спросите Jana о рабочих вопросах…" aria-label="Ваш вопрос Jana" maxLength={2000} disabled={busy || !api.janaAvailable} rows={2} /><button className="btn btn-primary" type="submit" disabled={busy || !api.janaAvailable || question.trim().length < 3} title="Отправить вопрос" aria-label="Отправить вопрос"><Icon name="send" size={17} /></button></div>
          <div className="support-composer-caption"><span>Enter — отправить · Shift + Enter — новая строка</span><span>{question.length} / 2000</span></div>
        </form>
      </section>
      <aside className="support-chat-aside"><section className="card"><h3>Как я могу помочь</h3><div className="support-aside-item"><Icon name="plane" size={18} /><span><strong>Отпуск и отдых</strong>Как подать заявку и отследить её статус</span></div><div className="support-aside-item"><Icon name="wallet" size={18} /><span><strong>Аванс</strong>Порядок оформления запроса на выплату</span></div><div className="support-aside-item"><Icon name="shield" size={18} /><span><strong>Правила компании</strong>Ответы из опубликованных HR-материалов</span></div></section><section className="card"><h3><Icon name="book" size={16} /> Проверяемые ответы</h3><p>В ответе будут указаны найденные источники. Если в базе нет подтверждённой информации, Jana предложит обратиться в HR.</p><div className="support-profile-divider" style={{ margin: '17px 0' }} /><p>Каждый вопрос рассматривается отдельно. При уточнении добавьте нужный контекст в новый вопрос.</p></section><section className="support-note"><Icon name="lock" size={17} /><p>Не отправляйте пароли и личные кадровые сведения. Ваши данные доступны в разделе <Link to="/profile">«Мой профиль»</Link>.</p></section></aside>
    </div>
  </div>;
}

function SourceDialog({ source, onClose }: { source: JanaAnswer['sources'][number]; onClose: () => void }) {
  const { api } = usePortal();
  const [article, setArticle] = useState<JanaArticle | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setArticle(null); setError(null);
    api.getJanaSource(source.id).then(value => { if (active) setArticle(value); }).catch(err => { if (active) setError(err); });
    return () => { active = false; };
  }, [api, source.id, attempt]);
  const originalUrl = article ? safeSourceUrl(article.source_url) : null;
  return <Modal title={source.title} onClose={onClose} wide>
    {error ? <ErrorState error={error} retry={() => setAttempt(value => value + 1)} /> : !article ? <LoadingState /> : <div className="support-source">
      <p className="muted">{article.source_title}</p>
      {source.excerpt && <><h3>Фрагмент из ответа</h3><blockquote>{source.excerpt}</blockquote></>}
      <h3>Полный материал</h3><div className="support-source-content">{article.content}</div>
      {originalUrl && <a className="btn btn-secondary" href={originalUrl} target="_blank" rel="noopener noreferrer">Открыть оригинал<Icon name="arrow-right" size={15} /></a>}
    </div>}
  </Modal>;
}
