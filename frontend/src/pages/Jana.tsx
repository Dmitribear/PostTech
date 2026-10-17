import { t, tx } from '../lib/i18n';
import { Escalation } from './Workspace';
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link } from 'react-router-dom';
import { usePortal } from '../context';
import { Avatar, Icon, PageHeader, Modal, LoadingState, ErrorState } from '../components/ui';
import { errorMessage } from '../lib/api';
import { formatDate } from '../lib/format';
import type { JanaAnswer, KnowledgeSource } from '../lib/types';
import './support.css';

type Message = { id: number; role: 'user'; text: string } | { id: number; role: 'jana'; result: JanaAnswer; question: string };
const prompts = [
  { text: 'Как оформить отпуск?', short: 'Оформить отпуск', icon: 'plane', href: '/calendar?select=1', action: 'Оформить отпуск' },
  { text: 'Как запросить аванс?', short: 'Запросить аванс', icon: 'wallet', href: '/requests/new?type=advance', action: 'Запросить аванс' },
  { text: 'Где посмотреть статус заявки?', short: 'Статус заявки', icon: 'clipboard', href: '/requests', action: 'Мои заявки' },
  { text: 'Кто видит мои кадровые данные?', short: 'Защита данных', icon: 'shield', href: '/profile', action: 'Мой профиль' },
];
function safeSourceUrl(url: string | null): string | null {
  if (!url) return null;
  try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null; }
  catch { return null; }
}

export default function Jana({ embedded = false, onClose }: { embedded?: boolean; onClose?: () => void } = {}) {
  const { api, profile, mode } = usePortal();
  const [escalation, setEscalation] = useState<{question:string;context:string}|null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sourceExcerpt, setSourceExcerpt] = useState<string | null>(null);
  const [sourceVersion,setSourceVersion] = useState<string|null>(null);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [source, setSource] = useState<KnowledgeSource | null>(null);
  const [sourceError, setSourceError] = useState<unknown>(null);
  const [sourceAttempt, setSourceAttempt] = useState(0);
  useEffect(() => { if (!sourceId) return; let active = true; setSource(null); setSourceError(null); api.getKnowledgeSource(sourceId,sourceVersion).then(value => { if (active) setSource(value); }).catch(e => { if (active) setSourceError(e); }); return () => { active = false; }; }, [api, sourceId, sourceVersion, sourceAttempt]);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const generation = useRef(0);
  const sending = useRef(false);
  const counter = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  useEffect(() => { if (embedded) composer.current?.focus(); }, [embedded]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [messages, busy]);
  async function ask(value: string) {
    const text = value.trim();
    if (sending.current || !api.janaAvailable) return;
    if (text.length < 3) { setError('Напишите вопрос длиной не менее трёх символов.'); return; }
    if (text.length > 2000) { setError('Сократите вопрос до 2000 символов.'); return; }
    const current = generation.current;
    const messageId = ++counter.current;
    sending.current = true; setBusy(true); setError(''); setQuestion('');
    setMessages(previous => [...previous, { id: messageId, role: 'user', text }]);
    try {
      const result = await api.askJana(text);
      if (current === generation.current) setMessages(previous => [...previous, { id: ++counter.current, role: 'jana', result, question: text }]);
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
  return <div className={`support-page support-jana-page${mode === 'demo' ? ' support-jana-demo' : ''}${embedded ? ' support-jana-embedded' : ''}`}>
    {!embedded && <PageHeader title="AI Jana" description={t("Помощник по рабочим вопросам")} />}
    {mode === 'demo' && <p className="support-demo-note">{api.janaAvailable ? t('Локальная модель использует учебные материалы. Это примеры, а не утверждённые правила JanaPost.') : t('Локальная Jana не подключена к этой демоверсии. Для ответов нужен запущенный сервер демонстрации.')}</p>}
    <div className="support-chat-layout">
      <section className="card support-chat" aria-label={t("Чат с AI Jana")}>
        <div className="support-chat-top"><div className="support-chat-identity"><span className="support-jana-icon"><Icon name="bot" size={21} /></span><div><h2>Jana</h2><p>{tx(mode === 'demo' ? 'Демонстрационная база знаний' : 'По материалам компании')}</p></div></div><button className="btn btn-ghost" disabled={busy || !messages.length} onClick={() => { generation.current += 1; setMessages([]); setError(''); setQuestion(''); composer.current?.focus(); }}><Icon name="plus" size={16} />{t("Новый диалог")}</button>{embedded && <button type="button" className="icon-btn support-widget-close" onClick={onClose} aria-label={t("Закрыть AI Jana")}><Icon name="x" size={19} /></button>}</div>
        {!messages.length && !busy ? <div className="support-chat-welcome"><div className="support-jana-icon"><Icon name="sparkles" size={31} /></div><h2>{t("Чем помочь?")}</h2><p>{t("Отпуск, аванс или правила компании — спросите Jana.")}</p><div className="support-prompts">{prompts.map(prompt => <button className="support-prompt" key={t(prompt.text)} aria-label={t(prompt.text)} disabled={!api.janaAvailable} onClick={() => void ask(t(prompt.text))}><Icon name={prompt.icon} size={20} /><span className="support-prompt-full">{t(prompt.text)}</span><span className="support-prompt-short" aria-hidden="true">{t(prompt.short)}</span><Icon name="arrow-right" size={15} /></button>)}</div></div> : <div className="support-chat-messages" role="log" aria-label={t("Сообщения диалога")} aria-live="polite" aria-relevant="additions text">
          {messages.map(message => <div key={message.id} className={`support-message ${message.role}`}>
            {message.role === 'user' ? <Avatar name={profile.full_name} size={29} /> : <span className="support-jana-icon"><Icon name="bot" size={18} /></span>}
            <div className="support-message-bubble"><span className="support-message-author">{tx(message.role === 'user' ? 'Вы' : 'AI Jana')}</span>{message.role === 'user' ? message.text : <><p className="support-answer-text">{message.result.answer}</p>{tx(message.result.sources.length > 0 && <div className="support-citations"><span className="support-citations-label">{t("Источники ответа")}</span>{tx(message.result.sources.map((source, index) => { const href = safeSourceUrl(source.url); return source.id ? <button className="support-citation" key={`${source.title}-${index}`} onClick={() => { setSourceExcerpt(source.excerpt || null); setSourceVersion(source.version||null); setSourceId(source.id!); }}><Icon name="file" size={12} />{tx(source.title)}<Icon name="arrow-right" size={11} /></button> : href ? <a className="support-citation" key={`${source.title}-${index}`} href={href} target="_blank" rel="noopener noreferrer"><Icon name="file" size={12} />{tx(source.title)}<Icon name="arrow-right" size={11} /></a> : <span className="support-citation" key={`${source.title}-${index}`}><Icon name="file" size={12} />{tx(source.title)}</span>; }))}</div>)}{message.result.grounded && !message.result.escalation_suggested && prompts.filter(prompt => message.question === prompt.text || message.question === t(prompt.text)).map(prompt => <Link key={prompt.href} className="btn btn-secondary support-answer-action" to={prompt.href}><Icon name={prompt.icon} size={16} />{t(prompt.action)}<Icon name="arrow-right" size={16} /></Link>)}{message.result.escalation_suggested && <button className="btn btn-secondary" onClick={() => setEscalation({question:message.question,context:message.result.answer})}>{t("Передать вопрос в HR")}</button>}</>}</div>
          </div>)}
          {tx(busy && <div className="support-message"><span className="support-jana-icon"><Icon name="bot" size={18} /></span><span className="support-chat-typing" role="status">{t("Ищу ответ в базе знаний…")}</span></div>)}
          <div ref={end} />
        </div>}
        <form className="support-chat-composer" onSubmit={submit}>
          {tx(error && <p className="support-inline-error" role="alert" style={{ marginBottom: 10 }}>{tx(error)}</p>)}
          <div className="support-composer-box"><textarea ref={composer} value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={keyDown} placeholder={t("Напишите вопрос…")} aria-label={t("Ваш вопрос Jana")} maxLength={2000} disabled={busy || !api.janaAvailable} rows={2} /><button className="btn btn-primary" type="submit" disabled={busy || !api.janaAvailable || question.trim().length < 3} title={t("Отправить вопрос")} aria-label={t("Отправить вопрос")}><Icon name="send" size={19} /></button></div>
          <div className="support-composer-caption"><span>{t("Не отправляйте пароли и личные данные")}</span><span>{tx(question.length)} / 2000</span></div>
        </form>
      </section>
      {!embedded && <details className="support-jana-help"><summary><Icon name="shield" size={15} />{t("Ответы с проверяемыми источниками")}<Icon name="chevron-down" size={14} /></summary><p>{t("Jana отвечает по базе знаний и показывает источники. Если ответа нет — направит в HR. Каждый вопрос рассматривается отдельно: добавляйте контекст при уточнении. Кадровые данные доступны в ")}<Link to="/profile">{t("профиле")}</Link>.</p><p>{t("Enter — отправить · Shift + Enter — новая строка.")}</p></details>}
    </div>
    {tx(escalation && <Escalation {...escalation} onClose={() => setEscalation(null)} />)}
    {sourceId && <Modal title={source?.source_title || "Источник ответа"} onClose={() => setSourceId(null)} wide>{sourceError ? <ErrorState error={sourceError} retry={() => setSourceAttempt(attempt => attempt + 1)} /> : !source ? <LoadingState /> : <><h2>{tx(source.title)}</h2><div className="source-metadata"><span>{tx(source.version ? `Версия ${source.version}` : 'Версия не указана')}</span>{tx(source.updated_at && <span>{t("Обновлён ")}{tx(formatDate(source.updated_at))}</span>)}<strong className={source.freshness === 'reviewed' ? 'source-reviewed' : 'source-unverified'}>{tx(source.freshness === 'reviewed' ? `Проверен ${formatDate(source.reviewed_at)}` : source.freshness === 'review_overdue' ? 'Требуется повторная проверка' : 'Дата проверки не указана')}</strong>{tx(source.review_due_at && <span>{t("Проверить до ")}{tx(formatDate(source.review_due_at))}</span>)}</div><>{sourceExcerpt && <section className="support-source"><h3>{t("Фрагмент из ответа")}</h3><blockquote>{sourceExcerpt}</blockquote></section>}<h3>{t("Полный материал")}</h3><div className="source-document">{source.content}</div></>{tx(safeSourceUrl(source.source_url) && <a className="text-link" href={safeSourceUrl(source.source_url)!} target="_blank" rel="noopener noreferrer">{t("Открыть оригинал")}<Icon name="arrow-right" size={14} /></a>)}</>}</Modal>}
  </div>;
}
