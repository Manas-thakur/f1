create table public.control_state (
    id smallint primary key default 1 check (id = 1),
    selected_car_id text not null default 'car-01' check (selected_car_id ~ '^car-[0-9]{2}$'),
    updated_at timestamp with time zone not null default now()
);

alter table public.control_state enable row level security;

revoke all on table public.control_state from anon, authenticated;
grant select, insert, update on table public.control_state to service_role;

insert into public.control_state (id, selected_car_id)
values (1, 'car-01');
