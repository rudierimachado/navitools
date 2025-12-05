# 📊 Tabelas do Módulo Gerenciamento Financeiro

## Tabelas Utilizadas pelo Sistema

### 1. **users** (Tabela Principal)
```
- id (PK)
- email (UNIQUE)
- password_hash
- created_at
```
**Descrição:** Usuários do sistema

---

### 2. **finance_configs** (Configuração Financeira)
```
- id (PK)
- user_id (FK → users)
- management_type (personal/family)
- family_name
- responsible_name
- setup_completed
- setup_step
- currency
- timezone
- created_at
- updated_at
```
**Descrição:** Configurações principais de cada usuário

---

### 3. **family_members** (Membros da Família)
```
- id (PK)
- config_id (FK → finance_configs)
- name
- role
- birth_date
- is_active
- created_at
```
**Descrição:** Membros da família (para gestão familiar)

---

### 4. **categories** (Categorias)
```
- id (PK)
- config_id (FK → finance_configs)
- name
- type (income/expense)
- icon
- color
- is_default
- is_active
- created_at
```
**Descrição:** Categorias de receitas e despesas

---

### 5. **transactions** (Transações)
```
- id (PK)
- user_id (FK → users)
- category_id (FK → categories)
- family_member_id (FK → family_members, nullable)
- description
- amount
- type (income/expense)
- transaction_date
- is_paid
- paid_date
- payment_method
- notes
- frequency
- is_recurring
- is_fixed
- recurring_transaction_id (FK → recurring_transactions, nullable)
- monthly_closure_id (FK → monthly_closures, nullable)
- is_auto_loaded
- created_at
- updated_at
```
**Descrição:** Todas as transações financeiras

---

### 6. **recurring_transactions** (Transações Recorrentes)
```
- id (PK)
- user_id (FK → users)
- category_id (FK → categories)
- description
- amount
- type (income/expense)
- frequency (monthly/weekly/yearly)
- day_of_month
- day_of_week
- start_date
- end_date
- is_active
- payment_method
- notes
- created_at
- updated_at
```
**Descrição:** Transações que se repetem (salário, aluguel, etc.)

---

### 7. **monthly_closures** (Fechamento Mensal)
```
- id (PK)
- user_id (FK → users)
- year
- month (1-12)
- status (open/closed)
- total_income
- total_expense
- balance
- closed_at
- created_at
- updated_at
```
**Descrição:** Rastreia cada mês encerrado com totais

---

### 8. **monthly_fixed_expenses** (Snapshot de Despesas Fixas)
```
- id (PK)
- monthly_closure_id (FK → monthly_closures)
- original_transaction_id (FK → transactions, nullable)
- description
- amount
- category_id (FK → categories)
- created_at
```
**Descrição:** Snapshot de despesas fixas copiadas para o próximo mês

---

### 9. **system_shares** (Compartilhamento do Sistema)
```
- id (PK)
- owner_id (FK → users)
- shared_user_id (FK → users, nullable)
- shared_email
- status (pending/accepted/rejected)
- access_level (viewer/editor/admin)
- created_at
- accepted_at
```
**Descrição:** Controla compartilhamento do sistema entre usuários

---

### 10. **login_audit** (Auditoria de Login)
```
- id (PK)
- user_id (FK → users, nullable)
- email
- ip_address
- user_agent
- succeeded
- message
- created_at
```
**Descrição:** Rastreia tentativas de login

---

## Resumo

| Tabela | Tipo | Descrição |
|--------|------|-----------|
| users | Core | Usuários do sistema |
| finance_configs | Config | Configurações financeiras |
| family_members | Config | Membros da família |
| categories | Master | Categorias de transações |
| transactions | Data | Transações financeiras |
| recurring_transactions | Data | Transações recorrentes |
| monthly_closures | Data | Fechamentos mensais |
| monthly_fixed_expenses | Data | Snapshot de despesas fixas |
| system_shares | Config | Compartilhamento entre usuários |
| login_audit | Log | Auditoria de acessos |

**Total: 10 tabelas principais**

## Relacionamentos Principais

```
users
├── finance_configs (1:1)
│   ├── family_members (1:N)
│   └── categories (1:N)
├── transactions (1:N)
│   ├── category (N:1)
│   ├── family_member (N:1, opcional)
│   ├── recurring_transaction (N:1, opcional)
│   └── monthly_closure (N:1, opcional)
├── recurring_transactions (1:N)
│   └── category (N:1)
├── monthly_closures (1:N)
│   └── monthly_fixed_expenses (1:N)
├── system_shares (1:N)
│   └── shared_user (N:1, opcional)
└── login_audit (1:N)
```
