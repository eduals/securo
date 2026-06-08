# Securo — IA, Agentes e Integração via MCP

Guia de como funciona a camada de IA do Securo e como conectar um agente
externo (como o seu **Hermes**) para **ler dados** e **registrar atividades**
(transações, categorias, orçamentos, metas, etc.) no dashboard.

---

## TL;DR — o caminho rápido pro Hermes

1. Ligue a feature de agentes no `.env`:
   ```env
   AGENTS_ENABLED=true
   COMPOSE_PROFILES=agents
   ```
   E suba: `docker compose up -d` (sobe o container `mcp-server`).
2. No Securo: **Settings → AI Agents → External MCP access → Generate token**.
   Copie o **token** (JWT) — ele **não é mostrado de novo**.
3. O endpoint do Hermes é:
   - **Produção (atrás do Traefik, domínio único):** `https://securo.pipedocs.app/mcp`
   - Dev/local (porta publicada): `http://SEU_HOST:8765/mcp`

   JSON-RPC 2.0 via `POST`. **Ignore** o `:8765` que o painel "External MCP
   access" imprime — em produção o MCP é roteado pelo Traefik no path `/mcp`
   do mesmo domínio do app (sem porta, com HTTPS).
4. Autentique toda chamada com `Authorization: Bearer <token>`.
5. Para registrar algo, use as tools `propose_*` em **duas chamadas**:
   1ª chamada = preview (sem `apply`), 2ª chamada = `apply: true` (executa).
   Veja [Registrando atividades](#5-registrando-atividades-o-fluxo-de-propose).

O Securo já documenta o snippet de conexão pra clientes estilo Claude/Cursor e
OpenAI na própria tela. O Hermes entra pelo **mesmo endpoint MCP**.

---

## 1. Visão geral da arquitetura

A IA do Securo é **opcional**, **self-hosted** e desligada por padrão (custo
zero quando off). Ela tem dois lados:

```
┌──────────────────────────────────────────────────────────────────┐
│                          SEU SERVIDOR SECURO                       │
│                                                                    │
│  ┌───────────────┐   JWT     ┌──────────────────────────────┐     │
│  │   backend     │ (interno) │        mcp-server            │     │
│  │  (FastAPI)    ├──────────▶│   JSON-RPC 2.0  POST /mcp    │     │
│  │               │           │   porta 8765                 │     │
│  │ runtime de    │           │                              │     │
│  │ agentes +     │           │  Tools:                      │     │
│  │ chat ⌘J +     │           │   • read  (list_*, get_*)    │     │
│  │ RAG           │           │   • propose_* (mutações)     │     │
│  └───────────────┘           └───────────────┬──────────────┘     │
│         ▲                                     │ usa os mesmos      │
│         │ providers (OpenAI/Anthropic/        │ services + DB do   │
│         │ Ollama/OpenAI-compat)               ▼ backend            │
│         │                            ┌──────────────────┐          │
│         │                            │   PostgreSQL     │          │
│         │                            └──────────────────┘          │
└─────────┼──────────────────────────────────────────────────────────┘
          │
          │  porta 8765 publicada no host (JWT obrigatório)
          ▼
   ┌──────────────────────────────────────────────────┐
   │  AGENTES EXTERNOS                                  │
   │  Claude Desktop · Cursor · n8n · OpenAI · HERMES  │
   └──────────────────────────────────────────────────┘
```

- **Runtime interno de agentes** (`backend/app/agents/`): o chat embutido no
  Securo (painel global ⌘J), com suporte a múltiplos providers de LLM
  (OpenAI, Anthropic, Ollama, OpenAI-compatible) e uma base de conhecimento
  RAG por agente.
- **MCP server embutido** (`backend/mcp_server/`): um container separado que
  expõe os dados e ações do Securo via **Model Context Protocol** (MCP). É por
  aqui que **qualquer** agente — interno ou externo, incluindo o Hermes —
  executa ferramentas.

O ponto-chave para você: **o Hermes não precisa falar com o runtime interno.
Ele fala direto com o MCP server**, exatamente como o Claude Desktop faria.

---

## 2. O que é o MCP server (o ponto de integração)

Arquivo: `backend/mcp_server/main.py`.

- É um app FastAPI próprio, rodando no container `mcp-server` (porta `8765`).
- Fala **JSON-RPC 2.0** sobre **HTTP `POST /mcp`**.
- Métodos suportados:
  - `initialize` — handshake do protocolo.
  - `tools/list` — lista todas as ferramentas disponíveis (com JSON Schema).
  - `tools/call` — executa uma ferramenta com `{ name, arguments }`.
- `GET /health` — healthcheck simples (`{"status":"ok","tools":N}`).

Toda requisição passa primeiro por `verify_request` (auth). Sem token válido,
retorna `401` antes de qualquer coisa.

### Por que um container separado?

Modularidade. Quem não usa a feature de agentes não paga custo nenhum — o
container `mcp-server` só sobe sob o profile `agents` do docker-compose. E como
a porta é publicada no host, agentes externos conseguem alcançá-lo depois de
gerar um token.

---

## 3. Autenticação (JWT)

Arquivos: `backend/mcp_server/auth.py` (verificação) e
`backend/app/agents/mcp/auth.py` (emissão).

- Todo request ao `/mcp` exige header `Authorization: Bearer <JWT>`.
- O JWT é **HS256**, assinado com `AGENTS_MCP_JWT_SECRET` (o mesmo segredo dos
  dois lados — runtime e mcp-server).
- Claims relevantes:
  | Claim | Significado |
  |-------|-------------|
  | `sub` | `user_id` — escopo do usuário dono dos dados |
  | `ws_id` | workspace (tenant) onde as tools operam |
  | `iss` | `securo-backend` |
  | `aud` | `securo-mcp` |
  | `exp` | expiração |
  | `ext` | `true` para tokens de agentes externos (Hermes cai aqui) |

### Tokens internos vs. externos

- **Internos**: o runtime de agentes do Securo cunha um JWT curtíssimo
  (TTL padrão **600s**) por chamada. Você não lida com isso.
- **Externos** (`ext: true`): você gera um token longo na UI
  (TTL padrão **90 dias**, configurável via `AGENTS_MCP_EXTERNAL_TTL_DAYS`).
  **É esse que o Hermes usa.**

> O token externo é **escopado a um único workspace** no momento da criação.
> Se você tem vários workspaces, troque o workspace ativo na UI **antes** de
> gerar o token, ou gere um token por workspace.

### Gerando o token do Hermes

Pela UI (recomendado): **Settings → AI Agents → "External MCP access" →
Generate token**. A tela mostra:

- o **token** (copie na hora — o Securo **não armazena** o token e não mostra
  de novo),
- o **endpoint** (`http(s)://SEU_HOST:8765/mcp`),
- um exemplo de `curl`,
- snippets de config prontos pra Claude Desktop/Code/Cursor e OpenAI.

Por baixo dos panos, a UI chama `POST /api/agents/mcp-tokens`
(`backend/app/agents/api/mcp_tokens.py`).

> **Revogação:** não há lista de revogação por token. Para invalidar **todos**
> os tokens externos, rotacione `AGENTS_MCP_JWT_SECRET` e reinicie.

---

## 4. Ferramentas disponíveis (tools)

Definidas em `backend/mcp_server/tools/`. Cada tool tem nome, descrição e um
JSON Schema de parâmetros — exatamente o que o `tools/list` devolve, então o
Hermes descobre tudo dinamicamente.

### Leitura (read-only) — nunca escrevem no banco

| Tool | O que faz |
|------|-----------|
| `list_accounts` | lista contas |
| `get_account_summary` | resumo de uma conta |
| `list_transactions` | transações com filtros ricos (data, valor, categoria, conta, moeda, tags, splits…) |
| `list_categories` | categorias |
| `list_payees` | beneficiários/pagadores |
| `list_budgets` / `get_budget_vs_actual` | orçamentos e realizado |
| `list_recurring_transactions` | transações recorrentes/assinaturas |
| `list_assets` | ativos |
| `list_goals` | metas |
| `list_groups` / `get_group_balances` / `list_group_settlements` | grupos estilo Splitwise |
| `get_net_worth` / `get_income_expenses` / `get_cash_flow` | relatórios |
| `get_dashboard_snapshot` | foto geral do dashboard |
| `aggregate` | agregações genéricas |
| `search_all` | busca geral |
| `search_knowledge_base` | RAG (base de conhecimento do agente) |

### Mutação (`propose_*`) — registram/alteram dados

| Tool | Registra/altera |
|------|-----------------|
| **`propose_create_transaction`** | **transação avulsa (o caso clássico do Hermes: "registre um gasto de R$50")** |
| `propose_categorize` | (re)categoriza transações |
| `propose_create_category` | nova categoria |
| `propose_create_budget` | novo orçamento |
| `propose_create_recurring_transaction` | nova recorrência/assinatura |
| `propose_update_recurring_transaction` | edita uma recorrência |
| `propose_cancel_recurring_transaction` | cancela/desativa recorrência |
| `propose_create_goal` | nova meta |
| `propose_create_payee_rule` | regra de auto-categorização |

Todas as tools são **escopadas ao usuário + workspace do token** — o Hermes
nunca enxerga ou escreve dados de outro tenant.

---

## 5. Registrando atividades: o fluxo de `propose_*`

Esse é o ponto mais importante para o Hermes, então leia com atenção.

As tools `propose_*` foram desenhadas para serem **seguras por padrão**: elas
**não escrevem no banco**. Elas devolvem um **preview** (um "diff") do que
*aconteceria*. No chat embutido do Securo, isso vira um card com botão
**Apply** que o usuário clica para confirmar.

Mas um agente externo (Hermes) **não tem botão Apply**. Para isso existe o
**fluxo de duas chamadas com `apply: true`**:

```
Hermes                          mcp-server
  │                                 │
  │ 1) tools/call propose_create_transaction
  │    (SEM apply)  ───────────────▶│  valida conta/categoria,
  │                                 │  calcula o preview
  │ ◀───────────── preview ─────────│  (NADA escrito no banco)
  │                                 │
  │  [Hermes mostra o preview ao usuário e pede confirmação]
  │                                 │
  │ 2) tools/call propose_create_transaction
  │    (MESMOS args + apply:true) ─▶│  executa de verdade
  │ ◀──── { applied:true, id } ─────│  (POST /api/transactions interno)
```

Regras embutidas (em `backend/mcp_server/tools/proposals.py`):

- `apply: true` **só funciona** se o token for **externo** (`ext: true`). O
  runtime interno ignora o flag (lá o Apply é a UI).
- **Nunca** mande `apply: true` na primeira chamada. Primeiro mostre o preview,
  só depois da confirmação do usuário envie a segunda chamada.
- Quando a resposta traz `applied: true` (e um `id`), aí sim a atividade foi
  **realmente registrada**. Sem isso, foi só preview.

> O sistema é explícito sobre isso na descrição das tools: descreva como
> *"preparei uma proposta…"* / *"aqui está um preview…"* — só diga
> *"registrei/criei/pronto"* quando a resposta tiver `applied: true`.

---

## 6. Passo a passo: conectando o Hermes

### Passo 0 — habilitar a feature

No `.env`:

```env
AGENTS_ENABLED=true
COMPOSE_PROFILES=agents
# opcional: expor na LAN (padrão é só localhost 127.0.0.1:8765)
# AGENTS_MCP_EXTERNAL_HOST_PORT=0.0.0.0:8765
# opcional: TTL do token externo em dias (padrão 90)
# AGENTS_MCP_EXTERNAL_TTL_DAYS=90
# IMPORTANTE em produção: troque o segredo
# AGENTS_MCP_JWT_SECRET=<um-segredo-forte-e-único>
```

Suba: `docker compose up -d`. Confira o health:

```bash
curl http://localhost:8765/health
# {"status":"ok","tools":29}
```

> Por padrão a porta `8765` só escuta em `127.0.0.1`. Se o Hermes roda em outra
> máquina, use `AGENTS_MCP_EXTERNAL_HOST_PORT=0.0.0.0:8765` (e proteja a rede —
> o JWT é a única barreira) ou coloque atrás de um proxy reverso com TLS.

### Passo 1 — gerar o token

Settings → AI Agents → External MCP access → **Generate token**. Guarde o
token nas credenciais do Hermes.

### Passo 2 — descobrir as ferramentas

```bash
curl -X POST http://SEU_HOST:8765/mcp \
  -H "Authorization: Bearer $SECURO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Isso devolve o catálogo completo (com schemas). O Hermes pode registrar essas
tools no próprio loop de tool-use.

### Passo 3 — descobrir a conta de destino

`propose_create_transaction` exige um `account_id`. Liste as contas primeiro:

```bash
curl -X POST http://SEU_HOST:8765/mcp \
  -H "Authorization: Bearer $SECURO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"list_accounts","arguments":{}}}'
```

(Idem `list_categories` se quiser categorizar.)

### Passo 4 — preview da atividade (1ª chamada, sem `apply`)

```bash
curl -X POST http://SEU_HOST:8765/mcp \
  -H "Authorization: Bearer $SECURO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
        "name":"propose_create_transaction",
        "arguments":{
          "description":"Almoço",
          "amount":50,
          "type":"debit",
          "account_id":"<UUID_DA_CONTA>",
          "date":"2026-06-08"
        }}}'
```

Resposta = um `preview` com `kind: "create_transaction"` e o `proposed{...}`.
**Nada foi gravado ainda.**

### Passo 5 — confirmar e executar (2ª chamada, com `apply: true`)

Depois que o usuário confirma no Hermes, repita os **mesmos** argumentos +
`"apply": true`:

```bash
curl -X POST http://SEU_HOST:8765/mcp \
  -H "Authorization: Bearer $SECURO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{
        "name":"propose_create_transaction",
        "arguments":{
          "description":"Almoço",
          "amount":50,
          "type":"debit",
          "account_id":"<UUID_DA_CONTA>",
          "date":"2026-06-08",
          "apply":true
        }}}'
```

Resposta com `"applied": true` e o `id` da transação = **registrado de verdade**.

---

## 7. Detalhes úteis pro `propose_create_transaction`

Campos (schema completo no `tools/list`):

| Campo | Obrigatório | Notas |
|-------|:-----------:|-------|
| `description` | sim | 1–500 chars |
| `amount` | sim | sempre **positivo**; a direção vem do `type` |
| `type` | sim | `debit` = despesa, `credit` = receita |
| `account_id` | sim | UUID (use `list_accounts`) |
| `category_id` | não | UUID (use `list_categories`) |
| `date` | não | `YYYY-MM-DD`; default = hoje |
| `currency` | não | default = moeda da conta |
| `notes` | não | texto livre |
| `group_id` + `splits` | não | rateio estilo Splitwise (precisam vir **juntos**) |
| `apply` | não | só externo; `true` executa |

**Splits (rateio em grupo):** `splits.share_type` pode ser `equal` (divide
igual entre os `members`), `exact` (`share_amount` por membro, soma = `amount`)
ou `percent` (`share_pct` por membro, soma = 100). Todos os membros têm que
pertencer ao `group_id`. Use `list_groups` para pegar os IDs.

---

## 8. Configuração (variáveis de ambiente)

Definidas em `docker-compose.yml` / `docker-compose.prod.yml` e lidas em
`backend/app/agents/config.py`.

| Variável | Default | Para que serve |
|----------|---------|----------------|
| `AGENTS_ENABLED` | `false` | liga/desliga toda a feature |
| `COMPOSE_PROFILES` | — | precisa conter `agents` pra subir o `mcp-server` |
| `AGENTS_MCP_JWT_SECRET` | `dev-...` | segredo que assina/verifica os JWTs — **troque em prod** |
| `AGENTS_MCP_EXTERNAL_TTL_DAYS` | `90` | validade do token externo (Hermes) |
| `AGENTS_MCP_EXTERNAL_HOST_PORT` | `127.0.0.1:8765` | bind da porta no host |
| `AGENTS_BUILTIN_MCP_URL` | `http://mcp-server:8765/mcp` | URL interna que o runtime usa |
| `AGENTS_EXTRA_MCP_SERVERS` | — | registra MCP servers adicionais no runtime |
| `AGENTS_DEFAULT_PROVIDER` / `_MODEL` | `ollama` / — | provider/modelo padrão do chat interno |
| `AGENTS_OPENAI_API_KEY` / `AGENTS_ANTHROPIC_API_KEY` / `AGENTS_OLLAMA_BASE_URL` / `AGENTS_OPENAI_COMPAT_*` | — | credenciais dos providers (só pro runtime interno) |

> As chaves de provider (`OPENAI`, `ANTHROPIC`, …) são para o **chat embutido**
> do Securo. O Hermes traz o próprio modelo — ele só consome as **tools** via
> MCP, não precisa dessas chaves.

---

## 9. Segurança — resumo

- **Sempre autenticado**: o `/mcp` rejeita qualquer chamada sem JWT válido.
- **Escopo por tenant**: token carrega `sub` (usuário) e `ws_id` (workspace);
  as tools filtram tudo por esse escopo. Sem vazamento entre usuários.
- **Mutação com confirmação**: `propose_*` só grava com `apply: true` **e**
  token externo. O design força o passo de revisão antes de escrever.
- **Sem armazenamento do token**: o Securo não guarda o token gerado — copie na
  hora. Revogação = rotacionar `AGENTS_MCP_JWT_SECRET`.
- **Exposição de rede**: a porta sai só em `localhost` por padrão. Para LAN/
  internet, ponha TLS na frente e trate o JWT como a credencial sensível que é.

---

## 10. Mapa dos arquivos (pra fuçar no código)

```
backend/
├─ mcp_server/                # o MCP server (container separado)
│  ├─ main.py                 # app FastAPI, JSON-RPC, /mcp e /health
│  ├─ auth.py                 # verify_request — valida o JWT
│  ├─ registry.py             # registro de tools (@tool, tools/list, tools/call)
│  └─ tools/
│     ├─ transactions.py      # list_transactions (read)
│     ├─ proposals.py         # TODAS as propose_* (mutações + apply)
│     ├─ accounts.py, categories.py, budgets.py, goals.py, groups.py,
│     ├─ payees.py, reports.py, aggregate.py, search.py, knowledge.py,
│     └─ lifecycle.py
└─ app/agents/                # runtime interno (chat ⌘J, providers, RAG)
   ├─ api/mcp_tokens.py       # POST /api/agents/mcp-tokens (gera token externo)
   ├─ mcp/auth.py             # mint_token — cunha os JWTs
   └─ config.py               # settings (env vars)

frontend/
└─ src/components/agents/mcp-external-panel.tsx   # tela "External MCP access"
```

---

*Documento gerado para orientar a integração do agente Hermes com o MCP
server embutido do Securo. Atualize-o se as tools ou o fluxo de auth mudarem.*
