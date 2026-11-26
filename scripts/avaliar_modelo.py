"""Script de avaliação do modelo local (Ollama) com os 40 chamados sintéticos."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.llm import classificar_chamado


async def avaliar() -> None:
    settings = get_settings()
    dataset_path = ROOT_DIR / "data" / "chamados_sinteticos.json"
    chamados = json.loads(dataset_path.read_text(encoding="utf-8"))

    total = len(chamados)
    acertos = 0
    json_validos = 0
    tempos: list[float] = []
    erros: list[dict[str, object]] = []

    print(f"Avaliando {total} chamados no modelo '{settings.model_name}' ({settings.ollama_url})...\n")

    for item in chamados:
        inicio = time.perf_counter()
        resultado = await classificar_chamado(item["descricao"], settings=settings)
        duracao = time.perf_counter() - inicio
        tempos.append(duracao)

        if resultado.classificacao_automatica:
            json_validos += 1

        esperado = item["categoria_esperada"]
        obtido = resultado.categoria
        if obtido.lower() == esperado.lower():
            acertos += 1
        else:
            erros.append(
                {
                    "id": item["id"],
                    "esperado": esperado,
                    "obtido": obtido,
                    "confianca": resultado.confianca,
                    "descricao": item["descricao"][:80],
                }
            )

    taxa_acerto = (acertos / total) * 100 if total else 0.0
    taxa_json = (json_validos / total) * 100 if total else 0.0
    tempo_medio = sum(tempos) / total if total else 0.0

    print("=== Resultado da Avaliação ===")
    print(f"Total de chamados:       {total}")
    print(f"Acerto da categoria:     {acertos}/{total} ({taxa_acerto:.1f}%)")
    print(f"JSON válido (sem fallback): {json_validos}/{total} ({taxa_json:.1f}%)")
    print(f"Tempo médio por chamado: {tempo_medio:.2f}s")
    print(f"Total de erros:          {len(erros)}")

    if erros:
        print("\n=== Lista de Erros ===")
        for erro in erros:
            print(
                f"- ID {erro['id']}: esperado='{erro['esperado']}', "
                f"obtido='{erro['obtido']}' (conf={erro['confianca']:.2f}) | {erro['descricao']}"
            )


if __name__ == "__main__":
    asyncio.run(avaliar())
