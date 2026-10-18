insert into public.courses(id,title,description,duration_minutes,material_markdown,quiz,active,category,audience,
    passing_score,publication_state,family_id,version,course_type,provider,external_url)
values
('42000000-0000-4000-8000-000000000001','Excel для работы',
 'Практика работы с таблицами на площадке Яндекс Практикума. Программа и условия доступа — по ссылке на курс.',
 0,'','[]',true,'Повышение квалификации','Все сотрудники',80,'published','42000000-0000-4000-8000-000000000001',1,
 'external','Яндекс Практикум','https://start.practicum.yandex/excel-for-work/'),
('42000000-0000-4000-8000-000000000002','Критическое мышление',
 'Развитие навыков анализа информации и принятия решений. Программа, продолжительность и условия доступа — на площадке.',
 0,'','[]',true,'Управленческие навыки','Специалисты и руководители',80,'published','42000000-0000-4000-8000-000000000002',1,
 'external','Яндекс Практикум','https://practicum.yandex.ru/thinking/')
on conflict(id) do nothing;
