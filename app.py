"""GeoLog: execute com streamlit run app.py. MongoDB padrão: localhost:27017."""

import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import GEOSPHERE, MongoClient
from pymongo.errors import PyMongoError


SQLITE_PATH = Path(__file__).with_name("logitech.db")
MOTORISTAS = [
    (1, "Carlos Andrade", "123456789", "Ativo"),
    (2, "Mariana Silva", "987654321", "Ativo"),
    (3, "Roberto Souza", "456789123", "Em Descanso"),
]
VEICULOS = [
    (101, "ABC-1A23", "Volvo FH 540", 1),
    (102, "XYZ-9876", "Scania R450", 2),
    (103, "KGB-4567", "Mercedes Actros", 3),
]
TELEMETRIA_SEED = [
    {"veiculo_id": 101,
     "location": {"type": "Point", "coordinates": [-34.873, -7.115]},
     "temperatura": 4.2, "velocidade": 65, "timestamp": "2026-09-11T10:00:00Z"},
    {"veiculo_id": 102,
     "location": {"type": "Point", "coordinates": [-34.832, -7.121]},
     "temperatura": -18.5, "velocidade": 85, "timestamp": "2026-09-11T10:05:00Z"},
    {"veiculo_id": 103,
     "location": {"type": "Point", "coordinates": [-34.950, -7.150]},
     "temperatura": 22.0, "velocidade": 0, "timestamp": "2026-09-11T09:45:00Z"},
]


def inicializar_sqlite(caminho=SQLITE_PATH):
    with sqlite3.connect(caminho) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS motoristas (
                id INTEGER PRIMARY KEY, nome TEXT NOT NULL,
                cnh TEXT NOT NULL UNIQUE, status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS veiculos (
                id INTEGER PRIMARY KEY, placa TEXT NOT NULL UNIQUE,
                modelo TEXT NOT NULL, motorista_id INTEGER NOT NULL,
                FOREIGN KEY (motorista_id) REFERENCES motoristas(id)
            );
        """)
        conn.executemany("INSERT OR IGNORE INTO motoristas VALUES (?, ?, ?, ?)", MOTORISTAS)
        conn.executemany("INSERT OR IGNORE INTO veiculos VALUES (?, ?, ?, ?)", VEICULOS)


def inicializar_mongo(colecao):
    colecao.create_index([("location", GEOSPHERE)])
    for registro in TELEMETRIA_SEED:
        documento = dict(registro)
        # BSON Date permite ordenar e agregar o histórico cronologicamente.
        documento["timestamp"] = datetime.fromisoformat(registro["timestamp"])
        colecao.update_one(
            {"_id": f"seed-{registro['veiculo_id']}"},
            {"$setOnInsert": documento}, upsert=True,
        )


@st.cache_resource
def conectar_mongo(uri):
    return MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)


def ler_cadastros(caminho=SQLITE_PATH):
    with sqlite3.connect(caminho) as conn:
        veiculos = pd.read_sql_query("""
            SELECT v.id AS veiculo_id, v.placa, v.modelo, m.nome, m.status
            FROM veiculos v JOIN motoristas m ON m.id = v.motorista_id
        """, conn)
        motoristas = pd.read_sql_query("SELECT * FROM motoristas", conn)
    return veiculos, motoristas


def ultimas_telemetrias(colecao):
    return list(colecao.aggregate([
        {"$sort": {"timestamp": -1, "_id": -1}},
        {"$group": {"_id": "$veiculo_id", "registro": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$registro"}},
    ]))


def buscar_por_raio(colecao, ultimas, latitude, longitude, raio_km):
    # Filtra somente os registros atuais: posições antigas não entram no raio.
    return list(colecao.find({
        "_id": {"$in": [registro["_id"] for registro in ultimas]},
        "location": {"$geoWithin": {
            "$centerSphere": [[longitude, latitude], raio_km / 6378.1]
        }},
    }))


def unir_dados(cadastros, registros):
    sensores = pd.DataFrame([
        {"veiculo_id": r["veiculo_id"], "temperatura": r["temperatura"],
         "velocidade": r["velocidade"], "longitude": r["location"]["coordinates"][0],
         "latitude": r["location"]["coordinates"][1], "timestamp": r["timestamp"]}
        for r in registros
    ], columns=["veiculo_id", "temperatura", "velocidade", "longitude", "latitude", "timestamp"])
    return cadastros.merge(sensores, on="veiculo_id", how="inner")


def simular_movimentacao(colecao, ultimas, cadastros):
    status = cadastros.set_index("veiculo_id")["status"].to_dict()
    novos = []
    for registro in ultimas:
        longitude, latitude = registro["location"]["coordinates"]
        ativo = status.get(registro["veiculo_id"]) == "Ativo"
        if ativo:
            longitude = (longitude + random.uniform(-0.003, 0.003) + 180) % 360 - 180
            latitude = max(-90, min(90, latitude + random.uniform(-0.003, 0.003)))
        novos.append({
            "veiculo_id": registro["veiculo_id"],
            "location": {"type": "Point", "coordinates": [longitude, latitude]},
            "temperatura": round(registro["temperatura"] + random.uniform(-0.5, 0.5), 2),
            "velocidade": random.randint(40, 100) if ativo else 0,
            "timestamp": max(datetime.now(timezone.utc),
                             registro["timestamp"].replace(tzinfo=timezone.utc) + timedelta(milliseconds=1)),
        })
    if novos:
        colecao.insert_many(novos)


def criar_mapa(dados, latitude, longitude, raio_km):
    mapa = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Marker([latitude, longitude], tooltip="Ponto de referência",
                  icon=folium.Icon(color="green", icon="flag")).add_to(mapa)
    circulo = folium.Circle([latitude, longitude], radius=raio_km * 1000,
                           color="blue", fill=True, fill_opacity=0.08).add_to(mapa)
    for row in dados.itertuples():
        popup = (f"{escape(row.placa)} — {escape(row.nome)}<br>"
                 f"Temperatura: {row.temperatura:.2f} °C<br>Velocidade: {row.velocidade} km/h")
        folium.Marker([row.latitude, row.longitude], popup=popup, tooltip=row.placa,
                      icon=folium.Icon(color="red" if row.velocidade > 80 else "blue",
                                       icon="truck", prefix="fa")).add_to(mapa)
    mapa.fit_bounds(circulo.get_bounds())
    return mapa


def exibir_aplicacao(colecao):
    cadastros, motoristas = ler_cadastros()
    ultimas = ultimas_telemetrias(colecao)
    st.sidebar.header("Busca por raio")
    latitude = st.sidebar.number_input("Latitude", -90.0, 90.0, -7.115, step=0.001, format="%.6f")
    longitude = st.sidebar.number_input("Longitude", -180.0, 180.0, -34.873, step=0.001, format="%.6f")
    raio = st.sidebar.slider("Raio de busca (km)", 0.1, 50.0, 10.0, step=0.1)
    if st.sidebar.button("Simular Movimentação"):
        simular_movimentacao(colecao, ultimas, cadastros)
        ultimas = ultimas_telemetrias(colecao)
        st.sidebar.success("Telemetria atualizada.")

    registros = buscar_por_raio(colecao, ultimas, latitude, longitude, raio)
    dados = unir_dados(cadastros, registros)
    st.caption("Mapa, tabela e indicadores consideram a última posição dos veículos dentro do raio.")
    a, b, c = st.columns(3)
    a.metric("Total de frotas ativas", int((dados["status"] == "Ativo").sum()))
    b.metric("Temperatura média da carga", f"{dados['temperatura'].mean():.2f} °C" if not dados.empty else "—")
    c.metric("Alertas de velocidade (> 80 km/h)", int((dados["velocidade"] > 80).sum()))
    st.caption("Frotas ativas: veículos vinculados a motoristas com status Ativo.")

    st.subheader("Localização dos veículos")
    st.iframe(criar_mapa(dados, latitude, longitude, raio).get_root().render(), height=500)
    st.caption("Marcadores vermelhos indicam velocidade acima de 80 km/h.")
    st.subheader("Visão unificada")
    if dados.empty:
        st.info("Nenhum veículo encontrado no raio selecionado.")
    tabela = dados.copy()
    tabela["Coordenadas Atualizadas"] = [
        f"{r.latitude:.6f}, {r.longitude:.6f}" for r in dados.itertuples()
    ]
    tabela = tabela.rename(columns={"nome": "Nome do Motorista", "placa": "Placa",
                                   "temperatura": "Última Temperatura (°C)",
                                   "velocidade": "Velocidade (km/h)"})
    st.dataframe(tabela[["Nome do Motorista", "Placa", "Última Temperatura (°C)",
                        "Velocidade (km/h)", "Coordenadas Atualizadas"]], hide_index=True)

    st.subheader("Histórico de temperatura por veículo")
    historico = list(colecao.find({"veiculo_id": {"$in": dados["veiculo_id"].tolist()}}, {"_id": 0}).sort("timestamp", 1))
    if historico:
        historico_df = pd.DataFrame(historico).merge(cadastros[["veiculo_id", "placa"]], on="veiculo_id")
        st.plotly_chart(px.line(historico_df, x="timestamp", y="temperatura", color="placa", markers=True,
                               labels={"timestamp": "Data/hora (UTC)", "temperatura": "Temperatura (°C)", "placa": "Placa"}))
    else:
        st.info("Sem histórico para os veículos selecionados.")
    st.subheader("Distribuição do status dos motoristas")
    st.caption("Todos os motoristas cadastrados, independentemente do raio.")
    distribuicao = motoristas.groupby("status").size().reset_index(name="quantidade")
    st.plotly_chart(px.pie(distribuicao, names="status", values="quantidade"))


def main():
    st.set_page_config(page_title="GeoLog", page_icon="🚚", layout="wide")
    st.title("GeoLog — Monitoramento Logístico")
    try:
        inicializar_sqlite()
        cliente = conectar_mongo(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
        cliente.admin.command("ping")
        colecao = cliente.geolog_db.telemetria
        inicializar_mongo(colecao)
        exibir_aplicacao(colecao)
    except PyMongoError:
        st.error("Não foi possível acessar o MongoDB. Inicie o servidor local ou confira MONGODB_URI e as permissões do banco geolog_db.")
    except sqlite3.Error as erro:
        st.error(f"Erro ao acessar o SQLite: {erro}")


if __name__ == "__main__":
    main()
