-- Fictional portal guidance, not an official company policy.
-- Apply after 0006. Only the named demonstration source is eligible for refresh.
insert into public.knowledge_articles(id,title,content,source_title,keywords,version)
values ('20000000-0000-4000-8000-000000000004','Где посмотреть статус заявки',
'В демо-прототипе откройте раздел «Мои заявки» или «Заявки» и выберите нужную карточку. Pending означает, что заявка ожидает рассмотрения, approved — одобрена, rejected — отклонена, cancelled — отозвана сотрудником. В карточке заявки отображается комментарий руководителя или HR, рассмотревшего заявку, если он указан. При изменении статуса создаётся уведомление для сотрудника. Срок рассмотрения демонстрационная база не устанавливает. AI Jana объясняет значения статусов, но не получает текущий статус вашей конкретной заявки: проверьте его в карточке.',
'Демо: статусы заявок',array['статус','заявка','комментарий','руководитель'],'2')
on conflict (id) do update set title=excluded.title,content=excluded.content,
    keywords=excluded.keywords,version=excluded.version
where knowledge_articles.source_title='Демо: статусы заявок'
  and knowledge_articles.content is distinct from excluded.content;
