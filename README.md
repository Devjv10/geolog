# GeoLog

Trabalho acadêmico de monitoramento logístico com Streamlit, SQLite e MongoDB.

## Executar

Requisitos: Python 3.12 ou superior e MongoDB local em `localhost:27017`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Com o MongoDB instalado, inicie-o em outro terminal:

```bash
mkdir -p .mongodb/data
mongod --dbpath .mongodb/data --bind_ip 127.0.0.1
```

Inicie a aplicação:

```bash
streamlit run app.py
```

Acesse http://localhost:8501. Para outro servidor MongoDB, defina a variável
`MONGODB_URI` antes de executar a aplicação.

O banco SQLite `logitech.db`, as tabelas, o seed do enunciado, a coleção
`geolog_db.telemetria` e o índice `2dsphere` são criados automaticamente.

## Funcionalidades

- Busca por raio sobre a última localização de cada veículo.
- Mapa interativo Folium e join em memória entre SQLite e MongoDB.
- KPIs de frota ativa, temperatura média e alertas acima de 80 km/h.
- Histórico de temperatura e distribuição de status com Plotly.
- Botão **Simular Movimentação**, com atualização do mapa e dashboard.

Os indicadores e o histórico consideram os veículos dentro do raio. O gráfico
de status considera todos os motoristas. Veículos com motoristas em descanso
permanecem parados na simulação.

Aplicação concentrada em `app.py`. Bancos locais, ambiente virtual e binários
não são versionados. O relatório PDF não faz parte desta entrega.

Testado com Python 3.14 e MongoDB Community 8.0.
