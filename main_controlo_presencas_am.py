# -*- coding: utf-8 -*-
"""
Plataforma de Controlo de Presenças da Assembleia Municipal
PySide6 + SQLite

Autor: Miguel Franco
Versão inicial funcional: gestão de mandatos, forças políticas, coligações,
membros efetivos/suplentes, sessões/reuniões, presenças, substituições,
justificações documentais, alertas legais e relatórios.

Instalação:
    pip install PySide6

Execução:
    python main_controlo_presencas_am.py
"""

from __future__ import annotations

import csv
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QDate, QSize
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Controlo de Presenças da Assembleia Municipal"
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "controlo_presencas_am.sqlite"
DOCS_DIR = APP_DIR / "documentos_presencas"

ESTADOS = {
    "P": "Presente",
    "R": "Representado/Substituído",
    "FJ": "Falta justificada",
    "FI": "Falta injustificada",
}

TIPOS_FORCA = ["Partido", "Coligação", "Independente/GCE"]
TIPOS_MEMBRO = ["Eleito diretamente", "Presidente de Junta", "Substituto/Suplente"]
TIPOS_SESSAO = ["Ordinária", "Extraordinária"]
UNIDADES_LEGAIS = ["Sessão", "Reunião"]


# =============================================================================
# Utilidades
# =============================================================================


def hoje_iso() -> str:
    return date.today().isoformat()


def agora_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in invalid else ch for ch in name)
    return cleaned.strip() or "documento"


def show_info(parent: QWidget, text: str) -> None:
    QMessageBox.information(parent, APP_NAME, text)


def show_warning(parent: QWidget, text: str) -> None:
    QMessageBox.warning(parent, APP_NAME, text)


def ask_confirm(parent: QWidget, text: str) -> bool:
    return QMessageBox.question(parent, APP_NAME, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


# =============================================================================
# Base de dados
# =============================================================================


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_schema()
        self.ensure_initial_data()

    def create_schema(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS mandatos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            designacao TEXT NOT NULL UNIQUE,
            data_inicio TEXT,
            data_fim TEXT,
            ativo INTEGER NOT NULL DEFAULT 0,
            observacoes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS forcas_politicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandato_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('Partido','Coligação','Independente/GCE')),
            sigla TEXT NOT NULL,
            nome TEXT NOT NULL,
            cor TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            observacoes TEXT,
            UNIQUE(mandato_id, sigla),
            FOREIGN KEY(mandato_id) REFERENCES mandatos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS coligacao_partidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coligacao_id INTEGER NOT NULL,
            partido_id INTEGER NOT NULL,
            UNIQUE(coligacao_id, partido_id),
            FOREIGN KEY(coligacao_id) REFERENCES forcas_politicas(id) ON DELETE CASCADE,
            FOREIGN KEY(partido_id) REFERENCES forcas_politicas(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS membros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandato_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            email TEXT,
            tipo_membro TEXT NOT NULL CHECK(tipo_membro IN ('Eleito diretamente','Presidente de Junta','Substituto/Suplente')),
            efetivo INTEGER NOT NULL DEFAULT 1,
            forca_id INTEGER,
            coligacao_id INTEGER,
            partido_id INTEGER,
            ordem_lista INTEGER,
            freguesia TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            observacoes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(mandato_id) REFERENCES mandatos(id) ON DELETE CASCADE,
            FOREIGN KEY(forca_id) REFERENCES forcas_politicas(id) ON DELETE SET NULL,
            FOREIGN KEY(coligacao_id) REFERENCES forcas_politicas(id) ON DELETE SET NULL,
            FOREIGN KEY(partido_id) REFERENCES forcas_politicas(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS sessoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mandato_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            titulo TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'Ordinária' CHECK(tipo IN ('Ordinária','Extraordinária')),
            unidade_legal TEXT NOT NULL DEFAULT 'Sessão' CHECK(unidade_legal IN ('Sessão','Reunião')),
            local TEXT,
            observacoes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mandato_id, data, titulo),
            FOREIGN KEY(mandato_id) REFERENCES mandatos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS presencas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sessao_id INTEGER NOT NULL,
            membro_id INTEGER NOT NULL,
            estado TEXT NOT NULL DEFAULT 'P' CHECK(estado IN ('P','R','FJ','FI')),
            substituido INTEGER NOT NULL DEFAULT 0,
            substituto_id INTEGER,
            data_justificacao TEXT,
            documento_justificacao TEXT,
            observacoes TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sessao_id, membro_id),
            FOREIGN KEY(sessao_id) REFERENCES sessoes(id) ON DELETE CASCADE,
            FOREIGN KEY(membro_id) REFERENCES membros(id) ON DELETE CASCADE,
            FOREIGN KEY(substituto_id) REFERENCES membros(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS anexos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            presenca_id INTEGER NOT NULL,
            caminho TEXT NOT NULL,
            nome_original TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(presenca_id) REFERENCES presencas(id) ON DELETE CASCADE
        );
        """
        self.conn.executescript(sql)
        self.conn.commit()

    def ensure_initial_data(self) -> None:
        row = self.fetchone("SELECT id FROM mandatos LIMIT 1")
        if row is None:
            self.execute(
                "INSERT INTO mandatos(designacao, data_inicio, data_fim, ativo, observacoes) VALUES (?,?,?,?,?)",
                ("2025-2029", "2025-10-01", "2029-10-31", 1, "Mandato criado automaticamente. Pode ser alterado no painel de configurações."),
            )
            self.set_config("mandato_ativo_id", str(self.last_id()))

        active = self.fetchone("SELECT id FROM mandatos WHERE ativo=1 ORDER BY id LIMIT 1")
        if active and not self.get_config("mandato_ativo_id"):
            self.set_config("mandato_ativo_id", str(active["id"]))

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> None:
        self.conn.executemany(sql, params)
        self.conn.commit()

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def last_id(self) -> int:
        return int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    def set_config(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO config(chave, valor) VALUES(?, ?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (key, value),
        )

    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.fetchone("SELECT valor FROM config WHERE chave=?", (key,))
        return row["valor"] if row else default

    def active_mandate_id(self) -> Optional[int]:
        value = self.get_config("mandato_ativo_id")
        if value and value.isdigit():
            exists = self.fetchone("SELECT id FROM mandatos WHERE id=?", (int(value),))
            if exists:
                return int(value)
        row = self.fetchone("SELECT id FROM mandatos WHERE ativo=1 ORDER BY id DESC LIMIT 1")
        return int(row["id"]) if row else None

    def set_active_mandate(self, mandate_id: int) -> None:
        self.execute("UPDATE mandatos SET ativo=0")
        self.execute("UPDATE mandatos SET ativo=1 WHERE id=?", (mandate_id,))
        self.set_config("mandato_ativo_id", str(mandate_id))

    def mandates(self) -> List[sqlite3.Row]:
        return self.fetchall("SELECT * FROM mandatos ORDER BY data_inicio, designacao")

    def forces(self, mandato_id: int, only_active: bool = True, tipo: Optional[str] = None) -> List[sqlite3.Row]:
        sql = "SELECT * FROM forcas_politicas WHERE mandato_id=?"
        params: List[Any] = [mandato_id]
        if only_active:
            sql += " AND ativo=1"
        if tipo:
            sql += " AND tipo=?"
            params.append(tipo)
        sql += " ORDER BY CASE tipo WHEN 'Coligação' THEN 1 WHEN 'Partido' THEN 2 ELSE 3 END, sigla"
        return self.fetchall(sql, params)

    def members(self, mandato_id: int, only_active: bool = True) -> List[sqlite3.Row]:
        sql = """
            SELECT m.*,
                   fp.sigla AS forca_sigla,
                   fp.nome AS forca_nome,
                   fp.tipo AS forca_tipo,
                   col.sigla AS coligacao_sigla,
                   part.sigla AS partido_sigla
            FROM membros m
            LEFT JOIN forcas_politicas fp ON fp.id=m.forca_id
            LEFT JOIN forcas_politicas col ON col.id=m.coligacao_id
            LEFT JOIN forcas_politicas part ON part.id=m.partido_id
            WHERE m.mandato_id=?
        """
        params: List[Any] = [mandato_id]
        if only_active:
            sql += " AND m.ativo=1"
        sql += " ORDER BY m.efetivo DESC, m.tipo_membro, COALESCE(m.ordem_lista,9999), m.nome"
        return self.fetchall(sql, params)

    def effective_members(self, mandato_id: int) -> List[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT m.*,
                   fp.sigla AS forca_sigla,
                   fp.nome AS forca_nome,
                   fp.tipo AS forca_tipo,
                   part.sigla AS partido_sigla,
                   col.sigla AS coligacao_sigla
            FROM membros m
            LEFT JOIN forcas_politicas fp ON fp.id=m.forca_id
            LEFT JOIN forcas_politicas part ON part.id=m.partido_id
            LEFT JOIN forcas_politicas col ON col.id=m.coligacao_id
            WHERE m.mandato_id=? AND m.ativo=1 AND m.efetivo=1
            ORDER BY CASE m.tipo_membro WHEN 'Eleito diretamente' THEN 1 WHEN 'Presidente de Junta' THEN 2 ELSE 3 END,
                     COALESCE(m.ordem_lista,9999), m.nome
            """,
            (mandato_id,),
        )

    def eligible_substitutes(
        self,
        mandato_id: int,
        member: sqlite3.Row,
        used_ids: Sequence[int] = (),
        current_id: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        params: List[Any] = [mandato_id]
        sql = """
            SELECT m.*,
                   fp.sigla AS forca_sigla,
                   part.sigla AS partido_sigla,
                   col.sigla AS coligacao_sigla
            FROM membros m
            LEFT JOIN forcas_politicas fp ON fp.id=m.forca_id
            LEFT JOIN forcas_politicas part ON part.id=m.partido_id
            LEFT JOIN forcas_politicas col ON col.id=m.coligacao_id
            WHERE m.mandato_id=? AND m.ativo=1 AND m.efetivo=0
        """

        # Regra operacional: primeiro procura substitutos da mesma força partidária.
        # Em coligação, usa o partido que propôs o membro ausente; só quando o membro não tem partido associado usa a força/lista.
        if member["partido_id"]:
            sql += " AND m.partido_id=?"
            params.append(member["partido_id"])
        elif member["forca_id"]:
            sql += " AND m.forca_id=?"
            params.append(member["forca_id"])

        exclude = [int(x) for x in used_ids if x and int(x) != int(current_id or 0)]
        if exclude:
            placeholders = ",".join("?" for _ in exclude)
            sql += f" AND m.id NOT IN ({placeholders})"
            params.extend(exclude)
        sql += " ORDER BY COALESCE(m.ordem_lista,9999), m.nome"
        return self.fetchall(sql, params)

    def sessions(self, mandato_id: int) -> List[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM sessoes WHERE mandato_id=? ORDER BY data DESC, id DESC",
            (mandato_id,),
        )

    def session_by_id(self, sessao_id: int) -> Optional[sqlite3.Row]:
        return self.fetchone("SELECT * FROM sessoes WHERE id=?", (sessao_id,))

    def attendance_for_session(self, sessao_id: int) -> Dict[int, sqlite3.Row]:
        rows = self.fetchall("SELECT * FROM presencas WHERE sessao_id=?", (sessao_id,))
        return {int(r["membro_id"]): r for r in rows}

    def upsert_attendance(
        self,
        sessao_id: int,
        membro_id: int,
        estado: str,
        substituido: int = 0,
        substituto_id: Optional[int] = None,
        data_justificacao: Optional[str] = None,
        documento_justificacao: Optional[str] = None,
        observacoes: str = "",
    ) -> int:
        self.execute(
            """
            INSERT INTO presencas(sessao_id, membro_id, estado, substituido, substituto_id, data_justificacao, documento_justificacao, observacoes, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sessao_id, membro_id) DO UPDATE SET
                estado=excluded.estado,
                substituido=excluded.substituido,
                substituto_id=excluded.substituto_id,
                data_justificacao=excluded.data_justificacao,
                documento_justificacao=excluded.documento_justificacao,
                observacoes=excluded.observacoes,
                updated_at=excluded.updated_at
            """,
            (
                sessao_id,
                membro_id,
                estado,
                substituido,
                substituto_id,
                data_justificacao,
                documento_justificacao,
                observacoes,
                agora_iso(),
            ),
        )
        row = self.fetchone("SELECT id FROM presencas WHERE sessao_id=? AND membro_id=?", (sessao_id, membro_id))
        return int(row["id"])

    def add_attachment(self, presenca_id: int, caminho: str, nome_original: str) -> None:
        self.execute(
            "INSERT INTO anexos(presenca_id, caminho, nome_original) VALUES(?,?,?)",
            (presenca_id, caminho, nome_original),
        )

    def stats_for_member(self, membro_id: int) -> Dict[str, Any]:
        rows = self.fetchall(
            """
            SELECT p.estado, s.data, s.unidade_legal
            FROM presencas p
            JOIN sessoes s ON s.id=p.sessao_id
            WHERE p.membro_id=?
            ORDER BY s.data ASC, s.id ASC
            """,
            (membro_id,),
        )
        stats = {
            "P": 0,
            "R": 0,
            "FJ": 0,
            "FI": 0,
            "presencas": 0,
            "fi_sessoes": 0,
            "fi_reunioes": 0,
            "consecutivas_sessoes": 0,
            "consecutivas_reunioes": 0,
        }
        cur_sess = 0
        cur_reun = 0
        max_sess = 0
        max_reun = 0
        for r in rows:
            estado = r["estado"]
            stats[estado] += 1
            if estado in ("P", "R"):
                stats["presencas"] += 1
            unidade = r["unidade_legal"] or "Sessão"
            if unidade == "Sessão":
                if estado == "FI":
                    stats["fi_sessoes"] += 1
                    cur_sess += 1
                else:
                    cur_sess = 0
                max_sess = max(max_sess, cur_sess)
            else:
                if estado == "FI":
                    stats["fi_reunioes"] += 1
                    cur_reun += 1
                else:
                    cur_reun = 0
                max_reun = max(max_reun, cur_reun)
        stats["consecutivas_sessoes"] = max_sess
        stats["consecutivas_reunioes"] = max_reun
        return stats

    def alert_rows(self, mandato_id: int) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        members = self.effective_members(mandato_id)
        for m in members:
            stats = self.stats_for_member(int(m["id"]))
            fi_s = stats["fi_sessoes"]
            fi_r = stats["fi_reunioes"]
            cs = stats["consecutivas_sessoes"]
            cr = stats["consecutivas_reunioes"]
            risco = cs >= 3 or fi_s >= 6 or cr >= 6 or fi_r >= 12
            alerta = cs >= 2 or fi_s >= 4 or cr >= 4 or fi_r >= 8
            if risco or alerta or stats["FI"] > 0:
                if risco:
                    nivel = "CRÍTICO"
                    texto = "Risco legal de perda de mandato: verificar comunicação e tramitação."
                elif alerta:
                    nivel = "ALERTA"
                    texto = "Aproximação dos limiares legais: acompanhar faltas injustificadas."
                else:
                    nivel = "INFO"
                    texto = "Existem faltas injustificadas registadas."
                if m["tipo_membro"] == "Presidente de Junta":
                    destino = "Comunicação à Assembleia de Freguesia; eventual comunicação posterior ao Ministério Público pela entidade competente quando relevante."
                else:
                    destino = "Comunicação ao Ministério Público competente quando em número relevante para efeitos legais."
                alerts.append(
                    {
                        "nivel": nivel,
                        "membro": m["nome"],
                        "tipo": m["tipo_membro"],
                        "forca": m["partido_sigla"] or m["forca_sigla"] or "",
                        "fi_total": stats["FI"],
                        "fi_sessoes": fi_s,
                        "fi_reunioes": fi_r,
                        "consecutivas_sessoes": cs,
                        "consecutivas_reunioes": cr,
                        "texto": texto,
                        "destino": destino,
                    }
                )

        # Alertas de quórum e documentos/justificações pendentes
        today = date.today()
        sessions = self.sessions(mandato_id)
        effective_count = len(members)
        for s in sessions:
            attendance = self.fetchall("SELECT estado FROM presencas WHERE sessao_id=?", (int(s["id"]),))
            if attendance:
                present = sum(1 for r in attendance if r["estado"] in ("P", "R"))
                if effective_count and present <= effective_count // 2:
                    alerts.append(
                        {
                            "nivel": "CRÍTICO",
                            "membro": "Sessão/Reunião",
                            "tipo": s["unidade_legal"],
                            "forca": "",
                            "fi_total": "",
                            "fi_sessoes": "",
                            "fi_reunioes": "",
                            "consecutivas_sessoes": "",
                            "consecutivas_reunioes": "",
                            "texto": f"Possível falta de quórum em {s['titulo']} ({s['data']}): {present}/{effective_count} presentes ou representados.",
                            "destino": "Confirmar ata e legalidade do funcionamento/deliberação.",
                        }
                    )

        pending = self.fetchall(
            """
            SELECT p.*, s.data AS data_sessao, s.titulo, m.nome
            FROM presencas p
            JOIN sessoes s ON s.id=p.sessao_id
            JOIN membros m ON m.id=p.membro_id
            WHERE s.mandato_id=? AND p.estado IN ('FJ','FI')
            """,
            (mandato_id,),
        )
        for p in pending:
            sess_date = parse_iso_date(p["data_sessao"])
            if not sess_date:
                continue
            limite = sess_date + timedelta(days=5)
            if p["estado"] == "FJ" and not p["documento_justificacao"]:
                alerts.append(
                    {
                        "nivel": "ALERTA",
                        "membro": p["nome"],
                        "tipo": "Justificação",
                        "forca": "",
                        "fi_total": "",
                        "fi_sessoes": "",
                        "fi_reunioes": "",
                        "consecutivas_sessoes": "",
                        "consecutivas_reunioes": "",
                        "texto": f"Falta justificada sem documento associado em {p['titulo']} ({p['data_sessao']}).",
                        "destino": "Anexar prova/documento ou completar observações da decisão da mesa.",
                    }
                )
            if p["estado"] == "FI" and today <= limite:
                alerts.append(
                    {
                        "nivel": "INFO",
                        "membro": p["nome"],
                        "tipo": "Prazo",
                        "forca": "",
                        "fi_total": "",
                        "fi_sessoes": "",
                        "fi_reunioes": "",
                        "consecutivas_sessoes": "",
                        "consecutivas_reunioes": "",
                        "texto": f"Falta marcada como injustificada, mas ainda dentro do prazo de 5 dias após {p['data_sessao']}.",
                        "destino": "Aguardar eventual pedido de justificação ou rever após termo do prazo.",
                    }
                )
        return alerts


# =============================================================================
# Componentes visuais auxiliares
# =============================================================================


class Card(QFrame):
    def __init__(self, title: str, value: str = "0", subtitle: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("CardSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

    def set_value(self, value: Any, subtitle: str = "") -> None:
        self.value.setText(str(value))
        if subtitle:
            self.subtitle.setText(subtitle)


class BaseTab(QWidget):
    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__()
        self.db = db
        self.main_window = main_window

    @property
    def mandato_id(self) -> Optional[int]:
        return self.main_window.current_mandate_id()

    def refresh(self) -> None:
        pass


# =============================================================================
# Dashboard
# =============================================================================


class DashboardTab(BaseTab):
    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__(db, main_window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Painel de controlo")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        cards = QHBoxLayout()
        self.card_membros = Card("Membros efetivos", "0", "Com direito/dever de presença")
        self.card_suplentes = Card("Substitutos/Suplentes", "0", "Disponíveis por força política")
        self.card_sessoes = Card("Sessões/Reuniões", "0", "Registadas no mandato")
        self.card_fi = Card("Faltas injustificadas", "0", "Total acumulado")
        for c in [self.card_membros, self.card_suplentes, self.card_sessoes, self.card_fi]:
            cards.addWidget(c)
        layout.addLayout(cards)

        info = QLabel(
            "Legenda operacional: P = Presente; R = Representado/Substituído; FJ = Falta Justificada; FI = Falta Injustificada. "
            "Os estados P e R contam como presença para efeitos de resumo operacional."
        )
        info.setWordWrap(True)
        info.setObjectName("Hint")
        layout.addWidget(info)

        self.alert_table = QTableWidget(0, 10)
        self.alert_table.setHorizontalHeaderLabels(
            [
                "Nível",
                "Membro/Objeto",
                "Tipo",
                "Força",
                "FI total",
                "FI sessões",
                "FI reuniões",
                "Seguidas sessões",
                "Seguidas reuniões",
                "Ação/Observação",
            ]
        )
        self.alert_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.alert_table.setAlternatingRowColors(True)
        self.alert_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(QLabel("Alertas e riscos"))
        layout.addWidget(self.alert_table, 1)

    def refresh(self) -> None:
        mid = self.mandato_id
        if not mid:
            return
        effective = self.db.effective_members(mid)
        all_members = self.db.members(mid)
        suplentes = [m for m in all_members if int(m["efetivo"] or 0) == 0 and int(m["ativo"] or 0) == 1]
        sessoes = self.db.sessions(mid)
        fi_total = self.db.fetchone(
            """
            SELECT COUNT(*) AS n
            FROM presencas p JOIN sessoes s ON s.id=p.sessao_id
            WHERE s.mandato_id=? AND p.estado='FI'
            """,
            (mid,),
        )["n"]
        self.card_membros.set_value(len(effective))
        self.card_suplentes.set_value(len(suplentes))
        self.card_sessoes.set_value(len(sessoes))
        self.card_fi.set_value(fi_total)

        alerts = self.db.alert_rows(mid)
        self.alert_table.setRowCount(len(alerts))
        for row, a in enumerate(alerts):
            values = [
                a["nivel"],
                a["membro"],
                a["tipo"],
                a["forca"],
                a["fi_total"],
                a["fi_sessoes"],
                a["fi_reunioes"],
                a["consecutivas_sessoes"],
                a["consecutivas_reunioes"],
                f"{a['texto']} {a['destino']}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (4, 5, 6, 7, 8):
                    item.setTextAlignment(Qt.AlignCenter)
                if a["nivel"] == "CRÍTICO":
                    item.setBackground(QColor("#FEE2E2"))
                elif a["nivel"] == "ALERTA":
                    item.setBackground(QColor("#FEF3C7"))
                elif a["nivel"] == "INFO":
                    item.setBackground(QColor("#E0F2FE"))
                self.alert_table.setItem(row, col, item)


# =============================================================================
# Configurações: Mandatos, Forças e Coligações
# =============================================================================


class ConfigTab(BaseTab):
    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__(db, main_window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Configurações do mandato e forças políticas")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.mandato_list = QListWidget()
        self.mandato_list.currentItemChanged.connect(self.load_selected_mandate)
        left_layout.addWidget(QLabel("Mandatos"))
        left_layout.addWidget(self.mandato_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)

        group_mandato = QGroupBox("Dados do mandato")
        form = QFormLayout(group_mandato)
        self.mandato_id_edit = QLineEdit()
        self.mandato_id_edit.setReadOnly(True)
        self.designacao_edit = QLineEdit()
        self.inicio_edit = QDateEdit()
        self.inicio_edit.setCalendarPopup(True)
        self.inicio_edit.setDisplayFormat("yyyy-MM-dd")
        self.fim_edit = QDateEdit()
        self.fim_edit.setCalendarPopup(True)
        self.fim_edit.setDisplayFormat("yyyy-MM-dd")
        self.obs_mandato = QTextEdit()
        self.obs_mandato.setMaximumHeight(70)
        self.ativo_check = QCheckBox("Mandato ativo")
        form.addRow("ID", self.mandato_id_edit)
        form.addRow("Designação", self.designacao_edit)
        form.addRow("Data início", self.inicio_edit)
        form.addRow("Data fim", self.fim_edit)
        form.addRow("", self.ativo_check)
        form.addRow("Observações", self.obs_mandato)
        btns = QHBoxLayout()
        self.btn_new_mandate = QPushButton("Novo")
        self.btn_save_mandate = QPushButton("Guardar mandato")
        self.btn_set_active = QPushButton("Definir como ativo")
        self.btn_new_mandate.clicked.connect(self.clear_mandate_form)
        self.btn_save_mandate.clicked.connect(self.save_mandate)
        self.btn_set_active.clicked.connect(self.set_active_mandate)
        btns.addWidget(self.btn_new_mandate)
        btns.addWidget(self.btn_save_mandate)
        btns.addWidget(self.btn_set_active)
        form.addRow(btns)
        right_layout.addWidget(group_mandato)

        group_forca = QGroupBox("Forças políticas do mandato")
        fl = QVBoxLayout(group_forca)
        fform = QHBoxLayout()
        self.forca_tipo = QComboBox()
        self.forca_tipo.addItems(TIPOS_FORCA)
        self.forca_sigla = QLineEdit()
        self.forca_sigla.setPlaceholderText("Ex.: PS, PSD, COLIGAÇÃO, IND.")
        self.forca_nome = QLineEdit()
        self.forca_nome.setPlaceholderText("Designação completa")
        self.forca_cor = QLineEdit()
        self.forca_cor.setPlaceholderText("#1D4ED8")
        self.btn_add_forca = QPushButton("Adicionar força")
        self.btn_add_forca.clicked.connect(self.add_force)
        fform.addWidget(self.forca_tipo)
        fform.addWidget(self.forca_sigla)
        fform.addWidget(self.forca_nome, 2)
        fform.addWidget(self.forca_cor)
        fform.addWidget(self.btn_add_forca)
        fl.addLayout(fform)
        self.forces_table = QTableWidget(0, 5)
        self.forces_table.setHorizontalHeaderLabels(["ID", "Tipo", "Sigla", "Nome", "Ativa"])
        self.forces_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.forces_table.setAlternatingRowColors(True)
        fl.addWidget(self.forces_table)
        right_layout.addWidget(group_forca, 1)

        group_col = QGroupBox("Composição das coligações")
        cl = QGridLayout(group_col)
        self.coligacao_combo = QComboBox()
        self.partido_combo = QComboBox()
        self.btn_add_partido_col = QPushButton("Associar partido à coligação")
        self.btn_add_partido_col.clicked.connect(self.add_party_to_coalition)
        self.coligacao_table = QTableWidget(0, 3)
        self.coligacao_table.setHorizontalHeaderLabels(["Coligação", "Partido", "Remover"])
        self.coligacao_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        cl.addWidget(QLabel("Coligação"), 0, 0)
        cl.addWidget(self.coligacao_combo, 0, 1)
        cl.addWidget(QLabel("Partido"), 1, 0)
        cl.addWidget(self.partido_combo, 1, 1)
        cl.addWidget(self.btn_add_partido_col, 0, 2, 2, 1)
        cl.addWidget(self.coligacao_table, 2, 0, 1, 3)
        right_layout.addWidget(group_col, 1)

        splitter.setSizes([260, 900])

    def refresh(self) -> None:
        self.load_mandates()
        self.load_forces()
        self.load_coalitions()

    def load_mandates(self) -> None:
        self.mandato_list.clear()
        active_id = self.db.active_mandate_id()
        for m in self.db.mandates():
            text = f"{m['designacao']}" + ("  ✓" if int(m["id"]) == int(active_id or 0) else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, int(m["id"]))
            self.mandato_list.addItem(item)
            if int(m["id"]) == int(active_id or 0):
                self.mandato_list.setCurrentItem(item)

    def load_selected_mandate(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem] = None) -> None:
        if not current:
            return
        mid = int(current.data(Qt.UserRole))
        m = self.db.fetchone("SELECT * FROM mandatos WHERE id=?", (mid,))
        if not m:
            return
        self.mandato_id_edit.setText(str(m["id"]))
        self.designacao_edit.setText(m["designacao"])
        self.inicio_edit.setDate(QDate.fromString(m["data_inicio"] or hoje_iso(), "yyyy-MM-dd"))
        self.fim_edit.setDate(QDate.fromString(m["data_fim"] or hoje_iso(), "yyyy-MM-dd"))
        self.ativo_check.setChecked(bool(m["ativo"]))
        self.obs_mandato.setPlainText(m["observacoes"] or "")
        self.load_forces()
        self.load_coalitions()

    def clear_mandate_form(self) -> None:
        self.mandato_id_edit.clear()
        self.designacao_edit.clear()
        self.inicio_edit.setDate(QDate.currentDate())
        self.fim_edit.setDate(QDate.currentDate().addYears(4))
        self.ativo_check.setChecked(False)
        self.obs_mandato.clear()

    def save_mandate(self) -> None:
        designacao = normalize_text(self.designacao_edit.text())
        if not designacao:
            show_warning(self, "Indique a designação do mandato.")
            return
        inicio = self.inicio_edit.date().toString("yyyy-MM-dd")
        fim = self.fim_edit.date().toString("yyyy-MM-dd")
        ativo = 1 if self.ativo_check.isChecked() else 0
        obs = self.obs_mandato.toPlainText().strip()
        mid_text = self.mandato_id_edit.text().strip()
        try:
            if mid_text:
                mid = int(mid_text)
                self.db.execute(
                    "UPDATE mandatos SET designacao=?, data_inicio=?, data_fim=?, ativo=?, observacoes=? WHERE id=?",
                    (designacao, inicio, fim, ativo, obs, mid),
                )
            else:
                self.db.execute(
                    "INSERT INTO mandatos(designacao, data_inicio, data_fim, ativo, observacoes) VALUES(?,?,?,?,?)",
                    (designacao, inicio, fim, ativo, obs),
                )
                mid = self.db.last_id()
            if ativo:
                self.db.set_active_mandate(mid)
            self.main_window.reload_mandate_combo(mid)
            self.refresh()
            show_info(self, "Mandato guardado com sucesso.")
        except sqlite3.IntegrityError as exc:
            show_warning(self, f"Não foi possível guardar o mandato: {exc}")

    def set_active_mandate(self) -> None:
        mid_text = self.mandato_id_edit.text().strip()
        if not mid_text:
            show_warning(self, "Selecione primeiro um mandato.")
            return
        mid = int(mid_text)
        self.db.set_active_mandate(mid)
        self.main_window.reload_mandate_combo(mid)
        self.refresh()
        show_info(self, "Mandato ativo atualizado.")

    def selected_mandate_in_form(self) -> Optional[int]:
        text = self.mandato_id_edit.text().strip()
        if text.isdigit():
            return int(text)
        return self.mandato_id

    def add_force(self) -> None:
        mid = self.selected_mandate_in_form()
        if not mid:
            show_warning(self, "Selecione ou crie um mandato.")
            return
        sigla = normalize_text(self.forca_sigla.text()).upper()
        nome = normalize_text(self.forca_nome.text())
        if not sigla or not nome:
            show_warning(self, "Indique a sigla e o nome da força política.")
            return
        try:
            self.db.execute(
                "INSERT INTO forcas_politicas(mandato_id, tipo, sigla, nome, cor, ativo) VALUES(?,?,?,?,?,1)",
                (mid, self.forca_tipo.currentText(), sigla, nome, normalize_text(self.forca_cor.text())),
            )
            self.forca_sigla.clear()
            self.forca_nome.clear()
            self.forca_cor.clear()
            self.load_forces()
            self.load_coalitions()
            self.main_window.refresh_all_tabs()
        except sqlite3.IntegrityError as exc:
            show_warning(self, f"Não foi possível adicionar a força política: {exc}")

    def load_forces(self) -> None:
        mid = self.selected_mandate_in_form()
        if not mid:
            return
        forces = self.db.forces(mid, only_active=False)
        self.forces_table.setRowCount(len(forces))
        for row, f in enumerate(forces):
            vals = [f["id"], f["tipo"], f["sigla"], f["nome"], "Sim" if f["ativo"] else "Não"]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if col == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.forces_table.setItem(row, col, item)

    def load_coalitions(self) -> None:
        mid = self.selected_mandate_in_form()
        if not mid:
            return
        self.coligacao_combo.clear()
        self.partido_combo.clear()
        for c in self.db.forces(mid, tipo="Coligação"):
            self.coligacao_combo.addItem(f"{c['sigla']} — {c['nome']}", int(c["id"]))
        for p in self.db.forces(mid, tipo="Partido"):
            self.partido_combo.addItem(f"{p['sigla']} — {p['nome']}", int(p["id"]))
        rows = self.db.fetchall(
            """
            SELECT cp.id, c.sigla AS coligacao, p.sigla AS partido, p.nome AS partido_nome
            FROM coligacao_partidos cp
            JOIN forcas_politicas c ON c.id=cp.coligacao_id
            JOIN forcas_politicas p ON p.id=cp.partido_id
            WHERE c.mandato_id=?
            ORDER BY c.sigla, p.sigla
            """,
            (mid,),
        )
        self.coligacao_table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            self.coligacao_table.setItem(row, 0, QTableWidgetItem(r["coligacao"]))
            self.coligacao_table.setItem(row, 1, QTableWidgetItem(f"{r['partido']} — {r['partido_nome']}"))
            btn = QPushButton("Remover")
            btn.setProperty("cp_id", int(r["id"]))
            btn.clicked.connect(self.remove_coligacao_partido)
            self.coligacao_table.setCellWidget(row, 2, btn)

    def add_party_to_coalition(self) -> None:
        col_id = self.coligacao_combo.currentData()
        part_id = self.partido_combo.currentData()
        if not col_id or not part_id:
            show_warning(self, "Selecione a coligação e o partido.")
            return
        try:
            self.db.execute(
                "INSERT INTO coligacao_partidos(coligacao_id, partido_id) VALUES(?,?)",
                (int(col_id), int(part_id)),
            )
            self.load_coalitions()
        except sqlite3.IntegrityError:
            show_warning(self, "Esse partido já está associado a essa coligação.")

    def remove_coligacao_partido(self) -> None:
        btn = self.sender()
        cp_id = int(btn.property("cp_id"))
        self.db.execute("DELETE FROM coligacao_partidos WHERE id=?", (cp_id,))
        self.load_coalitions()


# =============================================================================
# Membros
# =============================================================================


class MembersTab(BaseTab):
    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__(db, main_window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Membros da Assembleia Municipal e substitutos")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        form_box = QGroupBox("Ficha do membro")
        form_layout = QFormLayout(form_box)
        self.member_id = QLineEdit()
        self.member_id.setReadOnly(True)
        self.nome = QLineEdit()
        self.email = QLineEdit()
        self.tipo_membro = QComboBox()
        self.tipo_membro.addItems(TIPOS_MEMBRO)
        self.efetivo = QCheckBox("Membro efetivo da Assembleia Municipal")
        self.efetivo.setChecked(True)
        self.forca = QComboBox()
        self.coligacao = QComboBox()
        self.partido = QComboBox()
        self.ordem = QSpinBox()
        self.ordem.setRange(0, 9999)
        self.ordem.setSpecialValueText("-")
        self.freguesia = QLineEdit()
        self.ativo = QCheckBox("Ativo")
        self.ativo.setChecked(True)
        self.obs = QTextEdit()
        self.obs.setMaximumHeight(100)
        form_layout.addRow("ID", self.member_id)
        form_layout.addRow("Nome", self.nome)
        form_layout.addRow("Email", self.email)
        form_layout.addRow("Tipo", self.tipo_membro)
        form_layout.addRow("", self.efetivo)
        form_layout.addRow("Força/lista", self.forca)
        form_layout.addRow("Coligação", self.coligacao)
        form_layout.addRow("Partido que representa", self.partido)
        form_layout.addRow("Ordem/lista", self.ordem)
        form_layout.addRow("Freguesia", self.freguesia)
        form_layout.addRow("", self.ativo)
        form_layout.addRow("Observações", self.obs)
        btns = QHBoxLayout()
        self.btn_new = QPushButton("Novo")
        self.btn_save = QPushButton("Guardar")
        self.btn_deactivate = QPushButton("Desativar")
        self.btn_new.clicked.connect(self.clear_form)
        self.btn_save.clicked.connect(self.save_member)
        self.btn_deactivate.clicked.connect(self.deactivate_member)
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_deactivate)
        form_layout.addRow(btns)
        splitter.addWidget(form_box)

        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        search_line = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar por nome, email, partido ou freguesia...")
        self.search.textChanged.connect(self.populate_table)
        search_line.addWidget(QLabel("Pesquisa"))
        search_line.addWidget(self.search)
        table_layout.addLayout(search_line)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["ID", "Nome", "Tipo", "Efetivo", "Força", "Coligação", "Partido", "Ordem", "Email"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self.load_from_selection)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_box)
        splitter.setSizes([420, 900])

    def refresh(self) -> None:
        self.load_combo_data()
        self.populate_table()

    def load_combo_data(self) -> None:
        mid = self.mandato_id
        self.forca.clear()
        self.coligacao.clear()
        self.partido.clear()
        self.forca.addItem("—", None)
        self.coligacao.addItem("—", None)
        self.partido.addItem("—", None)
        if not mid:
            return
        for f in self.db.forces(mid, only_active=True):
            self.forca.addItem(f"{f['sigla']} — {f['nome']}", int(f["id"]))
        for c in self.db.forces(mid, only_active=True, tipo="Coligação"):
            self.coligacao.addItem(f"{c['sigla']} — {c['nome']}", int(c["id"]))
        for p in self.db.forces(mid, only_active=True, tipo="Partido"):
            self.partido.addItem(f"{p['sigla']} — {p['nome']}", int(p["id"]))

    def populate_table(self) -> None:
        mid = self.mandato_id
        if not mid:
            self.table.setRowCount(0)
            return
        term = self.search.text().lower().strip()
        rows = self.db.members(mid, only_active=False)
        if term:
            rows = [r for r in rows if term in " ".join(str(r[k] or "") for k in r.keys()).lower()]
        self.table.setRowCount(len(rows))
        for row, m in enumerate(rows):
            vals = [
                m["id"],
                m["nome"],
                m["tipo_membro"],
                "Sim" if m["efetivo"] else "Não",
                m["forca_sigla"] or "",
                m["coligacao_sigla"] or "",
                m["partido_sigla"] or "",
                m["ordem_lista"] if m["ordem_lista"] is not None else "",
                m["email"] or "",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if not m["ativo"]:
                    item.setForeground(QColor("#9CA3AF"))
                if col in (0, 3, 7):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)

    def set_combo_by_data(self, combo: QComboBox, data: Any) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def load_from_selection(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        m = self.db.fetchone("SELECT * FROM membros WHERE id=?", (int(id_item.text()),))
        if not m:
            return
        self.member_id.setText(str(m["id"]))
        self.nome.setText(m["nome"])
        self.email.setText(m["email"] or "")
        self.tipo_membro.setCurrentText(m["tipo_membro"])
        self.efetivo.setChecked(bool(m["efetivo"]))
        self.set_combo_by_data(self.forca, m["forca_id"])
        self.set_combo_by_data(self.coligacao, m["coligacao_id"])
        self.set_combo_by_data(self.partido, m["partido_id"])
        self.ordem.setValue(int(m["ordem_lista"] or 0))
        self.freguesia.setText(m["freguesia"] or "")
        self.ativo.setChecked(bool(m["ativo"]))
        self.obs.setPlainText(m["observacoes"] or "")

    def clear_form(self) -> None:
        self.member_id.clear()
        self.nome.clear()
        self.email.clear()
        self.tipo_membro.setCurrentIndex(0)
        self.efetivo.setChecked(True)
        self.forca.setCurrentIndex(0)
        self.coligacao.setCurrentIndex(0)
        self.partido.setCurrentIndex(0)
        self.ordem.setValue(0)
        self.freguesia.clear()
        self.ativo.setChecked(True)
        self.obs.clear()

    def save_member(self) -> None:
        mid = self.mandato_id
        if not mid:
            show_warning(self, "Selecione um mandato ativo.")
            return
        nome = normalize_text(self.nome.text())
        if not nome:
            show_warning(self, "Indique o nome do membro.")
            return
        data = (
            mid,
            nome,
            normalize_text(self.email.text()),
            self.tipo_membro.currentText(),
            1 if self.efetivo.isChecked() else 0,
            self.forca.currentData(),
            self.coligacao.currentData(),
            self.partido.currentData(),
            None if self.ordem.value() == 0 else self.ordem.value(),
            normalize_text(self.freguesia.text()),
            1 if self.ativo.isChecked() else 0,
            self.obs.toPlainText().strip(),
        )
        try:
            if self.member_id.text().strip():
                member_id = int(self.member_id.text())
                self.db.execute(
                    """
                    UPDATE membros SET mandato_id=?, nome=?, email=?, tipo_membro=?, efetivo=?, forca_id=?, coligacao_id=?, partido_id=?, ordem_lista=?, freguesia=?, ativo=?, observacoes=?
                    WHERE id=?
                    """,
                    data + (member_id,),
                )
            else:
                self.db.execute(
                    """
                    INSERT INTO membros(mandato_id, nome, email, tipo_membro, efetivo, forca_id, coligacao_id, partido_id, ordem_lista, freguesia, ativo, observacoes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    data,
                )
                self.member_id.setText(str(self.db.last_id()))
            self.populate_table()
            self.main_window.refresh_all_tabs()
            show_info(self, "Membro guardado com sucesso.")
        except sqlite3.IntegrityError as exc:
            show_warning(self, f"Não foi possível guardar o membro: {exc}")

    def deactivate_member(self) -> None:
        if not self.member_id.text().strip():
            show_warning(self, "Selecione um membro.")
            return
        if ask_confirm(self, "Pretende desativar este membro? O histórico será mantido."):
            self.db.execute("UPDATE membros SET ativo=0 WHERE id=?", (int(self.member_id.text()),))
            self.populate_table()
            self.main_window.refresh_all_tabs()


# =============================================================================
# Sessões e presenças
# =============================================================================


class SessionsTab(BaseTab):
    COL_MEMBER_ID = 0
    COL_NOME = 1
    COL_TIPO = 2
    COL_FORCA = 3
    COL_ESTADO = 4
    COL_SUBSTITUTO = 5
    COL_DATA_JUST = 6
    COL_DOC = 7
    COL_OBS = 8

    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__(db, main_window)
        self.loading_table = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Gestão das Assembleias Municipais")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        group = QGroupBox("Sessão/Reunião")
        form = QFormLayout(group)
        self.session_id = QLineEdit()
        self.session_id.setReadOnly(True)
        self.session_date = QDateEdit()
        self.session_date.setCalendarPopup(True)
        self.session_date.setDisplayFormat("yyyy-MM-dd")
        self.session_date.setDate(QDate.currentDate())
        self.session_title = QLineEdit()
        self.session_title.setPlaceholderText("Ex.: AM 29-11-2025")
        self.session_type = QComboBox()
        self.session_type.addItems(TIPOS_SESSAO)
        self.unidade_legal = QComboBox()
        self.unidade_legal.addItems(UNIDADES_LEGAIS)
        self.local = QLineEdit()
        self.session_obs = QTextEdit()
        self.session_obs.setMaximumHeight(80)
        form.addRow("ID", self.session_id)
        form.addRow("Data", self.session_date)
        form.addRow("Título", self.session_title)
        form.addRow("Tipo", self.session_type)
        form.addRow("Contagem legal", self.unidade_legal)
        form.addRow("Local", self.local)
        form.addRow("Observações", self.session_obs)
        btns = QHBoxLayout()
        self.btn_new_session = QPushButton("Nova")
        self.btn_save_session = QPushButton("Guardar")
        self.btn_delete_session = QPushButton("Apagar")
        self.btn_new_session.clicked.connect(self.clear_session_form)
        self.btn_save_session.clicked.connect(self.save_session)
        self.btn_delete_session.clicked.connect(self.delete_session)
        btns.addWidget(self.btn_new_session)
        btns.addWidget(self.btn_save_session)
        btns.addWidget(self.btn_delete_session)
        form.addRow(btns)
        left_layout.addWidget(group)

        left_layout.addWidget(QLabel("Sessões/Reuniões registadas"))
        self.sessions_list = QListWidget()
        self.sessions_list.currentItemChanged.connect(self.load_session_from_list)
        left_layout.addWidget(self.sessions_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        actions = QHBoxLayout()
        self.btn_load_members = QPushButton("Carregar membros efetivos")
        self.btn_save_attendance = QPushButton("Guardar presenças")
        self.btn_summary_txt = QPushButton("Gerar resumo TXT")
        self.btn_load_members.clicked.connect(self.load_attendance_table)
        self.btn_save_attendance.clicked.connect(self.save_attendance)
        self.btn_summary_txt.clicked.connect(self.export_session_summary)
        actions.addWidget(self.btn_load_members)
        actions.addWidget(self.btn_save_attendance)
        actions.addWidget(self.btn_summary_txt)
        actions.addStretch()
        right_layout.addLayout(actions)

        hint = QLabel(
            "No campo Substituto surgem apenas membros não efetivos elegíveis pela mesma força partidária. "
            "Quando o membro pertence a coligação e tem partido associado, a filtragem é feita pelo partido que representa; "
            "um substituto já escolhido na mesma sessão deixa de estar disponível nas restantes linhas."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        right_layout.addWidget(hint)

        self.att_table = QTableWidget(0, 9)
        self.att_table.setHorizontalHeaderLabels(["ID", "Membro", "Tipo", "Força/Partido", "Estado", "Substituto", "Data justificação", "Documento", "Observações"])
        self.att_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.att_table.setAlternatingRowColors(True)
        self.att_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.att_table.setColumnHidden(self.COL_MEMBER_ID, True)
        right_layout.addWidget(self.att_table, 1)
        splitter.addWidget(right)
        splitter.setSizes([350, 1000])

    def refresh(self) -> None:
        self.load_sessions_list()
        if self.session_id.text().strip():
            self.load_attendance_table()

    def clear_session_form(self) -> None:
        self.session_id.clear()
        self.session_date.setDate(QDate.currentDate())
        self.session_title.clear()
        self.session_type.setCurrentIndex(0)
        self.unidade_legal.setCurrentIndex(0)
        self.local.clear()
        self.session_obs.clear()
        self.att_table.setRowCount(0)

    def save_session(self) -> None:
        mid = self.mandato_id
        if not mid:
            show_warning(self, "Selecione um mandato ativo.")
            return
        titulo = normalize_text(self.session_title.text())
        if not titulo:
            titulo = f"AM {self.session_date.date().toString('dd-MM-yyyy')}"
            self.session_title.setText(titulo)
        data = self.session_date.date().toString("yyyy-MM-dd")
        values = (mid, data, titulo, self.session_type.currentText(), self.unidade_legal.currentText(), normalize_text(self.local.text()), self.session_obs.toPlainText().strip())
        try:
            if self.session_id.text().strip():
                sid = int(self.session_id.text())
                self.db.execute(
                    "UPDATE sessoes SET mandato_id=?, data=?, titulo=?, tipo=?, unidade_legal=?, local=?, observacoes=? WHERE id=?",
                    values + (sid,),
                )
            else:
                self.db.execute(
                    "INSERT INTO sessoes(mandato_id, data, titulo, tipo, unidade_legal, local, observacoes) VALUES(?,?,?,?,?,?,?)",
                    values,
                )
                sid = self.db.last_id()
                self.session_id.setText(str(sid))
            self.load_sessions_list(select_id=sid)
            self.load_attendance_table()
            self.main_window.refresh_all_tabs(except_tab=self)
            show_info(self, "Sessão/Reunião guardada com sucesso.")
        except sqlite3.IntegrityError as exc:
            show_warning(self, f"Não foi possível guardar a sessão/reunião: {exc}")

    def delete_session(self) -> None:
        if not self.session_id.text().strip():
            show_warning(self, "Selecione uma sessão/reunião.")
            return
        if ask_confirm(self, "Pretende apagar a sessão/reunião selecionada e todas as presenças associadas?"):
            self.db.execute("DELETE FROM sessoes WHERE id=?", (int(self.session_id.text()),))
            self.clear_session_form()
            self.load_sessions_list()
            self.main_window.refresh_all_tabs(except_tab=self)

    def load_sessions_list(self, select_id: Optional[int] = None) -> None:
        self.sessions_list.clear()
        mid = self.mandato_id
        if not mid:
            return
        for s in self.db.sessions(mid):
            item = QListWidgetItem(f"{s['data']} — {s['titulo']} ({s['unidade_legal']})")
            item.setData(Qt.UserRole, int(s["id"]))
            self.sessions_list.addItem(item)
            if select_id and int(s["id"]) == select_id:
                self.sessions_list.setCurrentItem(item)

    def load_session_from_list(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem] = None) -> None:
        if not current:
            return
        sid = int(current.data(Qt.UserRole))
        s = self.db.session_by_id(sid)
        if not s:
            return
        self.session_id.setText(str(s["id"]))
        self.session_date.setDate(QDate.fromString(s["data"], "yyyy-MM-dd"))
        self.session_title.setText(s["titulo"])
        self.session_type.setCurrentText(s["tipo"])
        self.unidade_legal.setCurrentText(s["unidade_legal"])
        self.local.setText(s["local"] or "")
        self.session_obs.setPlainText(s["observacoes"] or "")
        self.load_attendance_table()

    def selected_session_id(self) -> Optional[int]:
        text = self.session_id.text().strip()
        return int(text) if text.isdigit() else None

    def current_used_substitute_ids(self, ignore_row: Optional[int] = None) -> List[int]:
        used: List[int] = []
        for row in range(self.att_table.rowCount()):
            if ignore_row is not None and row == ignore_row:
                continue
            combo = self.att_table.cellWidget(row, self.COL_SUBSTITUTO)
            estado_combo = self.att_table.cellWidget(row, self.COL_ESTADO)
            if isinstance(combo, QComboBox) and isinstance(estado_combo, QComboBox):
                if estado_combo.currentData() == "R" and combo.currentData():
                    used.append(int(combo.currentData()))
        return used

    def make_status_combo(self, estado: str) -> QComboBox:
        combo = QComboBox()
        for code, label in ESTADOS.items():
            combo.addItem(f"{code} — {label}", code)
        idx = combo.findData(estado or "P")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(self.on_status_changed)
        return combo

    def make_substitute_combo(self, member: sqlite3.Row, current_sub_id: Optional[int], row_index: int) -> QComboBox:
        combo = QComboBox()
        combo.addItem("—", None)
        mid = self.mandato_id
        used = self.current_used_substitute_ids(ignore_row=row_index)
        if mid:
            for s in self.db.eligible_substitutes(mid, member, used, current_sub_id):
                sigla = s["partido_sigla"] or s["forca_sigla"] or ""
                combo.addItem(f"{s['nome']} ({sigla})", int(s["id"]))
        if current_sub_id:
            idx = combo.findData(int(current_sub_id))
            if idx < 0:
                sub = self.db.fetchone("SELECT nome FROM membros WHERE id=?", (int(current_sub_id),))
                if sub:
                    combo.addItem(f"{sub['nome']} (já selecionado/indisponível)", int(current_sub_id))
                    idx = combo.findData(int(current_sub_id))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(self.refresh_substitute_combos)
        return combo

    def load_attendance_table(self) -> None:
        sid = self.selected_session_id()
        mid = self.mandato_id
        if not sid:
            show_warning(self, "Guarde ou selecione primeiro uma sessão/reunião.")
            return
        if not mid:
            return
        self.loading_table = True
        members = self.db.effective_members(mid)
        attendance = self.db.attendance_for_session(sid)
        self.att_table.setRowCount(len(members))
        for row, m in enumerate(members):
            p = attendance.get(int(m["id"]))
            estado = p["estado"] if p else "P"
            sub_id = int(p["substituto_id"]) if p and p["substituto_id"] else None
            data_just = p["data_justificacao"] if p else ""
            doc = p["documento_justificacao"] if p else ""
            obs = p["observacoes"] if p else ""

            id_item = QTableWidgetItem(str(m["id"]))
            id_item.setData(Qt.UserRole, dict(m))
            self.att_table.setItem(row, self.COL_MEMBER_ID, id_item)
            self.att_table.setItem(row, self.COL_NOME, QTableWidgetItem(m["nome"]))
            self.att_table.setItem(row, self.COL_TIPO, QTableWidgetItem(m["tipo_membro"]))
            force_text = m["partido_sigla"] or m["forca_sigla"] or ""
            if m["coligacao_sigla"] and m["partido_sigla"]:
                force_text = f"{m['coligacao_sigla']} / {m['partido_sigla']}"
            self.att_table.setItem(row, self.COL_FORCA, QTableWidgetItem(force_text))

            status_combo = self.make_status_combo(estado)
            self.att_table.setCellWidget(row, self.COL_ESTADO, status_combo)

            sub_combo = self.make_substitute_combo(m, sub_id, row)
            self.att_table.setCellWidget(row, self.COL_SUBSTITUTO, sub_combo)

            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            if data_just:
                date_edit.setDate(QDate.fromString(data_just, "yyyy-MM-dd"))
            else:
                date_edit.setDate(QDate.currentDate())
            self.att_table.setCellWidget(row, self.COL_DATA_JUST, date_edit)

            doc_btn = QPushButton("Anexar" if not doc else "Ver/Alterar")
            doc_btn.setProperty("row", row)
            doc_btn.setProperty("path", doc or "")
            doc_btn.clicked.connect(self.attach_document)
            self.att_table.setCellWidget(row, self.COL_DOC, doc_btn)

            obs_item = QTableWidgetItem(obs or "")
            self.att_table.setItem(row, self.COL_OBS, obs_item)

            for col in (self.COL_NOME, self.COL_TIPO, self.COL_FORCA):
                self.att_table.item(row, col).setFlags(self.att_table.item(row, col).flags() & ~Qt.ItemIsEditable)

        self.att_table.resizeRowsToContents()
        self.loading_table = False
        self.apply_status_rules()
        self.refresh_substitute_combos()

    def on_status_changed(self) -> None:
        if self.loading_table:
            return
        self.apply_status_rules()
        self.refresh_substitute_combos()

    def apply_status_rules(self) -> None:
        for row in range(self.att_table.rowCount()):
            status_combo = self.att_table.cellWidget(row, self.COL_ESTADO)
            sub_combo = self.att_table.cellWidget(row, self.COL_SUBSTITUTO)
            date_edit = self.att_table.cellWidget(row, self.COL_DATA_JUST)
            doc_btn = self.att_table.cellWidget(row, self.COL_DOC)
            if not isinstance(status_combo, QComboBox):
                continue
            estado = status_combo.currentData()
            if isinstance(sub_combo, QComboBox):
                sub_combo.setEnabled(estado == "R")
                if estado != "R":
                    sub_combo.setCurrentIndex(0)
            if isinstance(date_edit, QDateEdit):
                date_edit.setEnabled(estado in ("FJ", "FI"))
            if isinstance(doc_btn, QPushButton):
                doc_btn.setEnabled(estado in ("FJ", "FI", "R"))

    def refresh_substitute_combos(self) -> None:
        if self.loading_table:
            return
        self.loading_table = True
        for row in range(self.att_table.rowCount()):
            id_item = self.att_table.item(row, self.COL_MEMBER_ID)
            if not id_item:
                continue
            member_dict = id_item.data(Qt.UserRole)
            if not member_dict:
                continue
            current_combo = self.att_table.cellWidget(row, self.COL_SUBSTITUTO)
            current_id = current_combo.currentData() if isinstance(current_combo, QComboBox) else None
            member_row = DictRow(member_dict)
            new_combo = self.make_substitute_combo(member_row, current_id, row)
            self.att_table.setCellWidget(row, self.COL_SUBSTITUTO, new_combo)
        self.loading_table = False
        self.apply_status_rules()

    def attach_document(self) -> None:
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        current_path = normalize_text(btn.property("path"))
        if current_path and Path(current_path).exists():
            choice = QMessageBox.question(
                self,
                APP_NAME,
                "Já existe um documento associado. Pretende abrir o ficheiro?\n\nEscolha 'Não' para selecionar outro ficheiro.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if choice == QMessageBox.Yes:
                os.startfile(current_path) if sys.platform.startswith("win") else os.system(f"xdg-open '{current_path}'")
                return
            if choice == QMessageBox.Cancel:
                return
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar documento", str(APP_DIR), "Documentos (*.pdf *.doc *.docx *.jpg *.jpeg *.png *.txt);;Todos os ficheiros (*.*)")
        if not path:
            return
        btn.setProperty("path", path)
        btn.setText("Ver/Alterar")

    def copy_document_for_row(self, row: int, presenca_id: int) -> Optional[str]:
        btn = self.att_table.cellWidget(row, self.COL_DOC)
        if not isinstance(btn, QPushButton):
            return None
        source = normalize_text(btn.property("path"))
        if not source:
            return None
        source_path = Path(source)
        if not source_path.exists():
            return source
        sid = self.selected_session_id() or 0
        dest_dir = DOCS_DIR / f"sessao_{sid}" / f"presenca_{presenca_id}"
        ensure_dir(dest_dir)
        dest = dest_dir / safe_filename(source_path.name)
        if source_path.resolve() != dest.resolve():
            base = dest.stem
            ext = dest.suffix
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{base}_{counter}{ext}"
                counter += 1
            shutil.copy2(str(source_path), str(dest))
        self.db.add_attachment(presenca_id, str(dest), source_path.name)
        return str(dest)

    def save_attendance(self) -> None:
        sid = self.selected_session_id()
        if not sid:
            show_warning(self, "Selecione primeiro uma sessão/reunião.")
            return
        errors: List[str] = []
        selected_subs: Dict[int, str] = {}
        for row in range(self.att_table.rowCount()):
            nome = self.att_table.item(row, self.COL_NOME).text() if self.att_table.item(row, self.COL_NOME) else f"Linha {row+1}"
            status_combo = self.att_table.cellWidget(row, self.COL_ESTADO)
            sub_combo = self.att_table.cellWidget(row, self.COL_SUBSTITUTO)
            if not isinstance(status_combo, QComboBox):
                continue
            estado = status_combo.currentData()
            sub_id = sub_combo.currentData() if isinstance(sub_combo, QComboBox) else None
            if estado == "R" and not sub_id:
                errors.append(f"{nome}: estado R exige indicação de substituto/representante.")
            if sub_id:
                if int(sub_id) in selected_subs:
                    errors.append(f"{nome}: substituto já selecionado para {selected_subs[int(sub_id)]}.")
                selected_subs[int(sub_id)] = nome
        if errors:
            show_warning(self, "Corrija antes de guardar:\n\n" + "\n".join(errors[:10]))
            return

        for row in range(self.att_table.rowCount()):
            member_id = int(self.att_table.item(row, self.COL_MEMBER_ID).text())
            status_combo = self.att_table.cellWidget(row, self.COL_ESTADO)
            sub_combo = self.att_table.cellWidget(row, self.COL_SUBSTITUTO)
            date_edit = self.att_table.cellWidget(row, self.COL_DATA_JUST)
            obs_item = self.att_table.item(row, self.COL_OBS)
            if not isinstance(status_combo, QComboBox):
                continue
            estado = str(status_combo.currentData())
            substituto_id = int(sub_combo.currentData()) if isinstance(sub_combo, QComboBox) and sub_combo.currentData() else None
            data_just = date_edit.date().toString("yyyy-MM-dd") if isinstance(date_edit, QDateEdit) and estado in ("FJ", "FI") else None
            obs = obs_item.text().strip() if obs_item else ""
            presenca_id = self.db.upsert_attendance(
                sid,
                member_id,
                estado,
                substituido=1 if estado == "R" else 0,
                substituto_id=substituto_id if estado == "R" else None,
                data_justificacao=data_just,
                documento_justificacao=None,
                observacoes=obs,
            )
            copied = self.copy_document_for_row(row, presenca_id)
            if copied:
                self.db.execute("UPDATE presencas SET documento_justificacao=? WHERE id=?", (copied, presenca_id))
        self.load_attendance_table()
        self.main_window.refresh_all_tabs(except_tab=self)
        show_info(self, "Presenças guardadas com sucesso.")

    def export_session_summary(self) -> None:
        sid = self.selected_session_id()
        if not sid:
            show_warning(self, "Selecione primeiro uma sessão/reunião.")
            return
        s = self.db.session_by_id(sid)
        rows = self.db.fetchall(
            """
            SELECT m.nome, m.tipo_membro, fp.sigla AS forca, part.sigla AS partido, p.estado, sub.nome AS substituto, p.data_justificacao, p.documento_justificacao, p.observacoes
            FROM presencas p
            JOIN membros m ON m.id=p.membro_id
            LEFT JOIN membros sub ON sub.id=p.substituto_id
            LEFT JOIN forcas_politicas fp ON fp.id=m.forca_id
            LEFT JOIN forcas_politicas part ON part.id=m.partido_id
            WHERE p.sessao_id=?
            ORDER BY m.tipo_membro, COALESCE(m.ordem_lista,9999), m.nome
            """,
            (sid,),
        )
        if not rows:
            show_warning(self, "Ainda não existem presenças guardadas para esta sessão/reunião.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Guardar resumo", str(APP_DIR / f"resumo_{safe_filename(s['titulo'])}.txt"), "Texto (*.txt)")
        if not dest:
            return
        lines = []
        lines.append(f"Resumo de presenças — {s['titulo']} — {s['data']}")
        lines.append("=" * 80)
        lines.append("")
        for r in rows:
            lines.append(f"{r['nome']} | {r['tipo_membro']} | {r['partido'] or r['forca'] or ''} | {r['estado']} - {ESTADOS.get(r['estado'], '')}")
            if r["substituto"]:
                lines.append(f"  Substituto/Representante: {r['substituto']}")
            if r["data_justificacao"]:
                lines.append(f"  Data justificação: {r['data_justificacao']}")
            if r["documento_justificacao"]:
                lines.append(f"  Documento: {r['documento_justificacao']}")
            if r["observacoes"]:
                lines.append(f"  Observações: {r['observacoes']}")
            lines.append("")
        Path(dest).write_text("\n".join(lines), encoding="utf-8")
        show_info(self, f"Resumo guardado em:\n{dest}")


class DictRow(dict):
    """Pequeno adaptador para permitir acesso tipo sqlite3.Row a dicionários."""

    def __getitem__(self, key: str) -> Any:
        return dict.get(self, key)


# =============================================================================
# Relatórios
# =============================================================================


class ReportsTab(BaseTab):
    def __init__(self, db: Database, main_window: "MainWindow"):
        super().__init__(db, main_window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Relatórios e exportações")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        actions = QHBoxLayout()
        self.btn_refresh = QPushButton("Atualizar relatório")
        self.btn_export_csv = QPushButton("Exportar CSV")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export_csv.clicked.connect(self.export_csv)
        actions.addWidget(self.btn_refresh)
        actions.addWidget(self.btn_export_csv)
        actions.addStretch()
        layout.addLayout(actions)

        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            [
                "Nome",
                "Tipo",
                "Força",
                "P",
                "R",
                "FJ",
                "FI",
                "Presenças",
                "FI sessões",
                "FI reuniões",
                "Seguidas sessões",
                "Estado legal",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        mid = self.mandato_id
        if not mid:
            return
        members = self.db.effective_members(mid)
        self.table.setRowCount(len(members))
        for row, m in enumerate(members):
            stats = self.db.stats_for_member(int(m["id"]))
            risco = stats["consecutivas_sessoes"] >= 3 or stats["fi_sessoes"] >= 6 or stats["consecutivas_reunioes"] >= 6 or stats["fi_reunioes"] >= 12
            alerta = stats["consecutivas_sessoes"] >= 2 or stats["fi_sessoes"] >= 4 or stats["consecutivas_reunioes"] >= 4 or stats["fi_reunioes"] >= 8
            estado_legal = "Risco de perda de mandato" if risco else "A acompanhar" if alerta else "Regular"
            vals = [
                m["nome"],
                m["tipo_membro"],
                m["partido_sigla"] or m["forca_sigla"] or "",
                stats["P"],
                stats["R"],
                stats["FJ"],
                stats["FI"],
                stats["presencas"],
                stats["fi_sessoes"],
                stats["fi_reunioes"],
                stats["consecutivas_sessoes"],
                estado_legal,
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if col >= 3 and col <= 10:
                    item.setTextAlignment(Qt.AlignCenter)
                if risco:
                    item.setBackground(QColor("#FEE2E2"))
                elif alerta:
                    item.setBackground(QColor("#FEF3C7"))
                self.table.setItem(row, col, item)

    def export_csv(self) -> None:
        mid = self.mandato_id
        if not mid:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Exportar CSV", str(APP_DIR / "relatorio_presencas_am.csv"), "CSV (*.csv)")
        if not dest:
            return
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        with open(dest, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            for row in range(self.table.rowCount()):
                writer.writerow([self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())])
        show_info(self, f"Relatório exportado para:\n{dest}")


# =============================================================================
# Janela principal
# =============================================================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ensure_dir(DOCS_DIR)
        self.db = Database(DB_PATH)
        self.setWindowTitle(APP_NAME)
        self.resize(1480, 900)
        self.setMinimumSize(QSize(1180, 720))

        self.toolbar = QToolBar("Principal")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.toolbar.addWidget(QLabel("Mandato ativo: "))
        self.mandate_combo = QComboBox()
        self.mandate_combo.setMinimumWidth(220)
        self.toolbar.addWidget(self.mandate_combo)
        self.mandate_combo.currentIndexChanged.connect(self.on_mandate_changed)
        refresh_action = QAction("Atualizar", self)
        refresh_action.triggered.connect(self.refresh_all_tabs)
        self.toolbar.addAction(refresh_action)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.dashboard_tab = DashboardTab(self.db, self)
        self.config_tab = ConfigTab(self.db, self)
        self.members_tab = MembersTab(self.db, self)
        self.sessions_tab = SessionsTab(self.db, self)
        self.reports_tab = ReportsTab(self.db, self)
        self.tabs.addTab(self.dashboard_tab, "Painel")
        self.tabs.addTab(self.config_tab, "Configurações")
        self.tabs.addTab(self.members_tab, "Membros")
        self.tabs.addTab(self.sessions_tab, "Assembleias Municipais")
        self.tabs.addTab(self.reports_tab, "Relatórios")
        self.tabs.currentChanged.connect(lambda _idx: self.current_tab_refresh())

        self.statusBar().showMessage(f"Base de dados: {DB_PATH}")
        self.reload_mandate_combo(self.db.active_mandate_id())
        self.refresh_all_tabs()

    def current_mandate_id(self) -> Optional[int]:
        data = self.mandate_combo.currentData()
        return int(data) if data else None

    def reload_mandate_combo(self, select_id: Optional[int] = None) -> None:
        self.mandate_combo.blockSignals(True)
        self.mandate_combo.clear()
        mandates = self.db.mandates()
        for m in mandates:
            self.mandate_combo.addItem(m["designacao"], int(m["id"]))
        if select_id:
            idx = self.mandate_combo.findData(int(select_id))
            if idx >= 0:
                self.mandate_combo.setCurrentIndex(idx)
        self.mandate_combo.blockSignals(False)

    def on_mandate_changed(self) -> None:
        mid = self.current_mandate_id()
        if mid:
            self.db.set_active_mandate(mid)
        self.refresh_all_tabs()

    def current_tab_refresh(self) -> None:
        tab = self.tabs.currentWidget()
        if hasattr(tab, "refresh"):
            tab.refresh()

    def refresh_all_tabs(self, except_tab: Optional[QWidget] = None) -> None:
        for idx in range(self.tabs.count()):
            tab = self.tabs.widget(idx)
            if tab is except_tab:
                continue
            if hasattr(tab, "refresh"):
                tab.refresh()


def build_stylesheet() -> str:
    return """
    QMainWindow, QWidget {
        background: #F8FAFC;
        color: #111827;
        font-family: Segoe UI, Arial, sans-serif;
        font-size: 10pt;
    }
    QToolBar {
        background: #FFFFFF;
        border-bottom: 1px solid #E5E7EB;
        padding: 6px;
        spacing: 8px;
    }
    QTabWidget::pane {
        border: 1px solid #E5E7EB;
        background: #FFFFFF;
        border-radius: 8px;
    }
    QTabBar::tab {
        background: #E5E7EB;
        padding: 8px 14px;
        margin-right: 3px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }
    QTabBar::tab:selected {
        background: #FFFFFF;
        color: #0F172A;
        font-weight: 600;
    }
    QLabel#PageTitle {
        font-size: 18pt;
        font-weight: 700;
        color: #0F172A;
        padding: 4px 0 10px 0;
    }
    QLabel#Hint {
        background: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 8px;
        padding: 8px;
        color: #1E3A8A;
    }
    QFrame#Card {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 12px;
    }
    QLabel#CardTitle {
        color: #64748B;
        font-size: 9pt;
        font-weight: 600;
    }
    QLabel#CardValue {
        color: #0F172A;
        font-size: 24pt;
        font-weight: 800;
    }
    QLabel#CardSubtitle {
        color: #64748B;
        font-size: 9pt;
    }
    QGroupBox {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        margin-top: 12px;
        padding: 12px;
        font-weight: 600;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 5px;
        color: #334155;
    }
    QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox {
        background: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 6px;
        padding: 5px;
        selection-background-color: #2563EB;
    }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {
        border: 1px solid #2563EB;
    }
    QPushButton {
        background: #1D4ED8;
        color: white;
        border: none;
        border-radius: 7px;
        padding: 7px 12px;
        font-weight: 600;
    }
    QPushButton:hover {
        background: #1E40AF;
    }
    QPushButton:disabled {
        background: #CBD5E1;
        color: #64748B;
    }
    QTableWidget, QListWidget {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        gridline-color: #E5E7EB;
        alternate-background-color: #F8FAFC;
    }
    QHeaderView::section {
        background: #F1F5F9;
        color: #334155;
        padding: 6px;
        border: 0px;
        border-bottom: 1px solid #CBD5E1;
        font-weight: 700;
    }
    QTableWidget::item:selected, QListWidget::item:selected {
        background: #DBEAFE;
        color: #0F172A;
    }
    """


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(build_stylesheet())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
