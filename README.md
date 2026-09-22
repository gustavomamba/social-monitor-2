# Social Monitor — Mamba Growth

Dashboard de tendências de redes sociais para os nichos **Weight Loss** e **Saúde Masculina**.

## Dashboard

- **URL:** https://social-monitor-v2.gustavo-266.workers.dev
- **Hospedagem:** Cloudflare Pages (projeto `social-monitor-v2`)
- **Deploy:** automático a cada push no `main` do repo `gustavomamba/social-monitor-v2`

## Automação

**Task Scheduler** roda `run_all.bat` todo dia às **02:00**.

Ordem de execução:
1. YouTube (`run_youtube.bat`)
2. Facebook (`run_facebook.bat`)
3. Google Trends (`run_trends.bat`)
4. TikTok Weight Loss (`run_tiktok.bat`)
5. TikTok Saúde Masculina (`run_tiktok_male.bat`)

Cada script que faz `git push` manda para os dois remotes (`origin` e `v2`). O `v2` aciona o deploy no Cloudflare automaticamente.

## Scripts

| Script | Fonte | Nicho |
|---|---|---|
| `scripts/fb_search.py` | Meta Ad Library API | Weight Loss |
| `scripts/apify_tiktok.py` | Apify | Weight Loss |
| `scripts/apify_tiktok_male.py` | Apify | Saúde Masculina |
| `scripts/yt_search.py` | YouTube Data API | Weight Loss |
| `scripts/trends.py` | Google Trends | Ambos |

### TikTok Saúde Masculina

- **14 keywords:** testosterone, kegel, erectile dysfunction, premature ejaculation, male performance, testosterone boost, kegel training, men sexual health, low testosterone, kegel exercises, desempenho masculino, testosterona, ereção, ejaculação precoce
- **10 vídeos por keyword**, mínimo 80K views
- **5 perfis monitorados:** @the_coach_app, @dr.kegel.app, @kegelmenapp, @latteboy868, @saludmasculinametodo

### Facebook Ads

Pipeline de 7 etapas:
1. Coleta via Meta Ad Library API
2. Captura de thumbnails
3. Filtro de texto (Claude API)
4. Filtro visual (Claude API)
5. Análise cruzada
6. Salvar + git push
7. Cache bust

> Requer `ANTHROPIC_API_KEY` no `.env`. Quando os créditos acabam, todos os anúncios passam sem filtro.

## Estrutura de Dados

```
data/
  YYYY-MM-DD.json   # arquivo do dia
  latest.json       # cópia do mais recente (usado pelo dashboard)
  history.json      # lista de datas disponíveis

dashboard/
  index.html        # dashboard completo
  logo.png          # logo Mamba Growth
  data/             # espelho dos arquivos de data (servido pelo Cloudflare)
```

### Formato dos arquivos JSON

```json
{
  "data_execucao": "22/09/2026 15:58",
  "youtube":  [...],
  "tiktok":   [...],
  "facebook": [...],
  "trends":   [...]
}
```

Campo `nicho` nos itens TikTok:
- `male_health` → aparece no nicho Saúde Masculina
- sem campo / `weight_loss` → aparece no nicho Weight Loss

## Dashboard — Como usar

- **Modo padrão:** mostra `latest.json` (dia atual)
- **7 dias / 30 dias:** agrega arquivos individuais do período
- **Nicho:** dropdown no topo para alternar entre Weight Loss e Saúde Masculina
- No nicho Saúde Masculina as abas Facebook Ads e Google Trends ficam ocultas

## Repositórios

| Remote | URL |
|---|---|
| `origin` | github.com/gustavomamba/social-monitor-2 |
| `v2` (Cloudflare) | github.com/gustavomamba/social-monitor-v2 |

Clone local: `C:\Users\Gustavo Henrique\social-monitor-2`

## Problemas Conhecidos

- **Facebook zerou:** verificar créditos da API Anthropic em `console.anthropic.com/billing`
- **Dashboard vazio no modo padrão:** normal quando a coleta do dia não gerou dados — usar filtro de 7 dias para ver histórico
