import { Link } from 'react-router-dom';
import { Icon, PageHeader } from '../components/ui';
import { t } from '../lib/i18n';

function Links({ items }: { items: string[][] }) {
  return <div className="workspace-links">{items.map(([path, icon, title, description]) => <Link key={path} to={path}><Icon name={icon} size={23} /><div><h2>{t(title)}</h2><p>{t(description)}</p></div><Icon name="chevron-right" size={18} /></Link>)}</div>;
}
export function Help() {
  return <><PageHeader title={t('Помощь')} /><Links items={[
    ['/jana', 'message', 'Спросить Jana', 'Ответы по отпуску, выплатам и правилам компании'],
    ['/support', 'users', 'Обращения в HR', 'Задать вопрос специалисту и посмотреть ответ'],
  ]} /></>;
}
export function HrTools() {
  return <><PageHeader title={t('Инструменты HR')} /><Links items={[
    ['/operations', 'briefcase', 'Управление HR', 'Остатки отпусков, база знаний и интеграции'],
    ['/delegations', 'users', 'Замещение', 'Кто согласует заявки в отсутствие руководителя'],
    ['/course-editor', 'book', 'Редактор курсов', 'Материалы, уроки и тесты'],
    ['/support', 'message', 'Обращения в HR', 'Вопросы сотрудников'],
  ]} /></>;
}
