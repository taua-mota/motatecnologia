# Portfolio - MotaTecnologia

Landing page simples para portfólio pessoal, com destaque para:

- apresentação profissional
- stack e foco técnico
- projetos estáticos alinhados ao README do GitHub
- projeto SHK Contabilidade adicionado manualmente
- links de contato

## Analytics de acessos (self-hosted com SQLite)

Este projeto possui analytics próprio, sem Umami e sem dependência externa.

Stack de analytics:

- frontend envia eventos para `/api/track`
- backend Python (`server.py`) persiste em SQLite
- painel de consulta em `/dashboard` protegido por autenticação

Dados coletados:

- pageviews e visitantes únicos (por sessão/IP)
- páginas mais acessadas
- origem de acesso (`referrer`)
- eventos de clique (CTAs)
- IP, user-agent, idioma, timezone e viewport dos últimos acessos

Sobre "quem acessou":

- você não terá nome da pessoa automaticamente
- terá IP e dados técnicos de acesso
- para identificar nominalmente, precisa de login/evento custom no seu produto

## Rodar local

### Opção 1: Python local

```bash
export ANALYTICS_USERNAME='admin'
export ANALYTICS_PASSWORD='troque-por-uma-senha-forte'
python3 server.py
```

Depois acesse:

- Site: `http://localhost:8080`
- Dashboard: `http://localhost:8080/dashboard`

### Opção 2: Docker

```bash
docker build -t motatecnologia-portfolio .
docker run --rm -p 8080:80 \
  -e ANALYTICS_USERNAME='admin' \
  -e ANALYTICS_PASSWORD='troque-por-uma-senha-forte' \
  -v "$(pwd)/data:/app/data" \
  motatecnologia-portfolio
```

Depois acesse:

- Site: `http://localhost:8080`
- Dashboard: `http://localhost:8080/dashboard`

Ao abrir o dashboard, o navegador pedirá usuário e senha (Basic Auth).

## Deploy via Traefik (`cornfield-hosted-apps`)

Exemplo de servico para adicionar no `docker-compose.yml` do seu projeto `cornfield-hosted-apps`:

```yaml
services:
  motatecnologia:
    build:
      context: /projects/motatecnologia
    container_name: motatecnologia
    restart: unless-stopped
    environment:
      - ANALYTICS_USERNAME=admin
      - ANALYTICS_PASSWORD=troque-por-uma-senha-forte
      - ANALYTICS_DB_PATH=/app/data/analytics.db
    volumes:
      - /projects/motatecnologia/data:/app/data
    labels:
      - traefik.enable=true
      - traefik.http.routers.motatecnologia.rule=Host(`motatecnologia.com`) || Host(`www.motatecnologia.com`)
      - traefik.http.routers.motatecnologia.entrypoints=websecure
      - traefik.http.routers.motatecnologia.tls=true
      - traefik.http.services.motatecnologia.loadbalancer.server.port=80
    networks:
      - traefik-public

networks:
  traefik-public:
    external: true
```

Ajuste:

- host (`motatecnologia.com` e `www.motatecnologia.com`)
- `context` para o caminho real do repositório no host
- nome da rede usada no seu ambiente Traefik
- volume de dados para persistir o SQLite
- usuário/senha de acesso ao dashboard (`ANALYTICS_USERNAME` e `ANALYTICS_PASSWORD`)

## CI/CD (GitHub Actions)

Workflow: `.github/workflows/deploy.yml`

Fluxo:

1. build da imagem Docker
2. push para `mott4a/motatecnologia-app:latest`
3. deploy via SSH no servidor em `/opt/motatecnologia`
4. espera o healthcheck do container `motatecnologia-app`

Secrets necessários no repositório:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `SERVER_HOST`
- `SERVER_SSH_KEY`

## Segurança

- Se `ANALYTICS_USERNAME` e `ANALYTICS_PASSWORD` não forem definidos, `/dashboard` e `/api/stats` ficam desabilitados.
- O endpoint de ingestão `/api/track` continua público para registrar visitas.
- Arquivos sensíveis (`/data`, `.db`, `server.py`, `.git`, `.codex`) não são servidos via HTTP.

## Fonte das referências

O conteúdo da página foi alinhado ao perfil público em:

- https://github.com/taua-mota
- https://github.com/taua-mota/taua-mota
