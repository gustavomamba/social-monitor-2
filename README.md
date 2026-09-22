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

---

## Scripts

| Script | Fonte | Nicho |
|---|---|---|
| `scripts/fb_search.py` | Meta Ad Library API | Weight Loss |
| `scripts/apify_tiktok.py` | Apify | Weight Loss |
| `scripts/apify_tiktok_male.py` | Apify | Saúde Masculina |
| `scripts/yt_search.py` | YouTube Data API | Weight Loss |
| `scripts/trends.py` | Google Trends | Ambos |

---

## Facebook Ads — Pipeline de 7 Etapas

### ETAPA 1 — Coleta
Busca na Meta Ad Library API por keywords de emagrecimento nos países UK, US e Alemanha.

### ETAPA 2 — Captura de Thumbnails
Baixa frames de vídeo (em segundos chave) e imagens dos anúncios para análise visual.

### ETAPA 3 — Filtro de Texto (Claude API)

**APROVADO (YES)** se o texto do anúncio é primariamente sobre:
- Perda de peso, queima de gordura ou truque/hack natural de emagrecimento
- Medicamentos GLP-1 (Ozempic, Mounjaro, semaglutide) ou alternativas naturais (berberina, etc.)
- História pessoal de transformação ou perda de peso
- Alimento, ingrediente ou hábito natural usado para emagrecer
- Supressão de apetite, aceleração do metabolismo ou redução de gordura abdominal

**REJEITADO (NO)** se o tema central é:
- Queda ou crescimento de cabelo
- Skincare, anti-aging ou tratamentos de pescoço/rosto
- Sono, ansiedade ou saúde mental (sem relação com peso)
- Diabetes sem ângulo de perda de peso
- Roupas ou moda
- Serviço B2B (agência de marketing, consultor de anúncios)
- Mau hálito, saúde intestinal ou digestão como tema principal

> Mencionar marcas (Ozempic, Mounjaro, berberina, GLP-1) é permitido e não causa rejeição.

### ETAPA 4 — Filtro Visual (Claude API multimodal)

**DESCARTADO** se qualquer um dos itens abaixo for verdade:
- Nenhuma pessoa real visível (objetos, roupas na cama, comida no prato, só texto)
- Profissional de saúde como personagem principal (médico, enfermeira, cientista de jaleco)
- Imagens médicas (raio-x, ilustrações de órgãos, diagramas científicos)
- Produto mostrado explicitamente (frasco, pílula, embalagem, nome da marca)
- Imagem sem conexão com perda de peso (lifestyle genérico, viagem, moda sem transformação corporal)

**APROVADO** se passar no filtro visual, retorna análise com:
- **Formato:** Receita / UGC / Talking Head / Antes-Depois / Animado / Texto em Tela
- **Avatar:** quem aparece e contexto (ex: mulher na cozinha, homem fazendo gelatina)
- **Edição:** estilo visual
- **Observação:** algo incomum ou fora do padrão
- **Destaque:** algo promissor ou que vale testar

### ETAPA 5 — Análise Cruzada
Claude analisa todos os anúncios aprovados juntos e identifica padrões, mecanismos em alta e avatares recorrentes.

### ETAPA 6 — Salvar + Git Push
Merge do resultado no `latest.json` e arquivo datado. Push para `origin` e `v2`.

### ETAPA 7 — Cache Bust
Commit vazio para forçar atualização do CDN.

---

## TikTok Saúde Masculina

**Keywords (10 vídeos por keyword, mínimo 80K views):**
testosterone, kegel, erectile dysfunction, premature ejaculation, male performance, testosterone boost, kegel training, men sexual health, low testosterone, kegel exercises, desempenho masculino, testosterona, ereção, ejaculação precoce

**Perfis monitorados (até 50 vídeos por perfil):**
@the_coach_app, @dr.kegel.app, @kegelmenapp, @latteboy868, @saludmasculinametodo

---

## TikTok Weight Loss

Busca por keywords de emagrecimento via Apify. Mínimo de views configurado no script.

---

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
  "trends":   []
}
```

Campo `nicho` nos itens TikTok:
- `male_health` → aparece no nicho Saúde Masculina
- sem campo ou `weight_loss` → aparece no nicho Weight Loss

---

## Dashboard — Como usar

- **Modo padrão:** mostra `latest.json` (dia atual)
- **7 dias / 30 dias:** agrega arquivos individuais do período
- **Nicho:** dropdown no topo para alternar entre Weight Loss e Saúde Masculina
- No nicho Saúde Masculina as abas Facebook Ads e Google Trends ficam ocultas

---

## Repositórios

| Remote | URL |
|---|---|
| `origin` | github.com/gustavomamba/social-monitor-2 |
| `v2` (Cloudflare) | github.com/gustavomamba/social-monitor-v2 |

Clone local: `C:\Users\Gustavo Henrique\social-monitor-2`

---

## Problemas Conhecidos

- **Facebook zerou:** verificar créditos da API Anthropic em `console.anthropic.com/billing`. Quando os créditos acabam, o ETAPA 3 e ETAPA 4 são pulados e todos os anúncios passam sem filtro — o resultado fica incorreto.
- **Dashboard vazio no modo padrão:** normal quando a coleta do dia não gerou dados. Usar filtro de 7 dias para ver histórico.
