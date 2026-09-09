# Binance Market Analyzer

Sistema read-only de analise tecnica para Binance. Ele consulta apenas dados publicos de mercado, gera cenarios condicionais e envia alertas informativos. Nenhuma ordem real e enviada.

## Segurança

- `TRADING_MODE=analysis_only` e o modo padrao.
- A inicializacao e bloqueada se `TRADING_MODE` for configurado como `live`, `real`, `trade`, `trading`, `execution` ou outro modo fora de `analysis_only`/`paper`.
- O fluxo principal nao chama endpoints privados de conta, criacao de ordem, cancelamento, margem, futures ou alavancagem.
- Chaves Binance sao opcionais para analise publica e devem ficar somente em variaveis de ambiente.
- `PAPER_TRADING=true`/`TRADING_MODE=paper` e reservado para simulacao local; ainda nao envia ordens reais.

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `.env` conforme os ativos e alertas desejados.

## Execução

```powershell
python main.py
```

Ao iniciar pelo `main.py`, o servidor local do dashboard tambem e iniciado e o navegador abre automaticamente em `http://127.0.0.1:8765`.

Dashboard local sem iniciar o loop principal do bot:

```powershell
python analysis_api.py
```

Acesse `http://127.0.0.1:8765`. O dashboard usa REST publico da Binance para carga inicial, WebSocket publico para candles em tempo real e, quando servido por `analysis_api.py`, tambem pode consultar `/api/signal` para obter sinais calculados pelo backend Python.

Diagnostico publico:

```powershell
python diagnostic.py
```

Testes:

```powershell
pytest
node --test tests/dashboard.test.mjs
```

## Variáveis principais

- `TRADING_MODE=analysis_only`
- `SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT`
- `CONTEXT_TIMEFRAME=4h`
- `CONFIRMATION_TIMEFRAME=1h`
- `SETUP_TIMEFRAME=15m`
- `REFINEMENT_TIMEFRAME=5m`
- `KLINE_LIMIT=250`
- `MAX_SPREAD_FILTER=0.003`
- `MIN_VOLUME_RATIO=0.50`
- `MIN_QUOTE_VOLUME_USDT=100000`
- `MIN_RISK_REWARD=2`
- `STOP_LOSS_PERCENT=0.02`
- `ALERT_COOLDOWN_SECONDS=900`

## Dashboard

O dashboard fica em `dashboard/index.html` e e separado em modulos:

- `marketData`: REST publico, WebSocket publico, reconexao e DEMO.
- `indicators`: EMA 9/21/50/200, RSI, MACD, ATR, VWAP, volume, suporte e resistencia.
- `signalEngine`: decisoes `LONG_SETUP`, `SHORT_SETUP`, `WAIT` e `INVALIDATED`.
- `chart`: Lightweight Charts com candles, EMAs, volume e linhas tecnicas.
- `alerts`: alertas visuais com cooldown.
- `storage`: preferencias e historico local no navegador.
- `ui`: filtros, estados, cards, painel de decisao e historico.

Ative o modo DEMO no seletor da interface para testar sem conexao com a Binance. Nenhuma chave Binance e armazenada no HTML ou JavaScript.

## Saída da análise

Cada ciclo retorna apenas:

- `LONG_SETUP`
- `SHORT_SETUP`
- `WAIT`
- `INVALIDATED`

Cada sinal inclui ativo, data/hora, preco atual, direcao predominante, tendencia por periodo, score, justificativa, regiao de entrada, stop tecnico, alvos, risco/retorno, nivel de invalidacao, condicoes de entrada, condicoes de cancelamento e aviso educacional.

`STOP_LOSS_PERCENT` define a distancia minima operacional do stop em relacao a referencia de entrada. Com `0.02`, uma configuracao valida nao usa stop menor que 2%; se o ATR, suporte ou resistencia exigirem mais espaco, o stop fica mais distante.

## Limitações

Analise tecnica nao garante lucro. O sistema nao decide nem executa operacoes reais; qualquer decisao operacional fora deste software e responsabilidade do usuario.
