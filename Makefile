# GEOIA - Comandos útiles (Mac/Linux/Windows + WSL)
# Uso: make <comando>

.PHONY: setup run download-models status help

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m  %-20s\033[0m %s\n", $$1, $$2}'

setup: ## Crea entorno virtual e instala dependencias
	python3 -m geoia.cli setup --dev

run: ## Inicia el servidor GEOIA
	python3 -m geoia.cli run

run-debug: ## Inicia el servidor en modo debug (recarga automática)
	python3 -m geoia.cli run --debug --reload

download-models: ## Descarga modelos de IA localmente
	python3 -m geoia.cli download-models

status: ## Muestra estado del sistema y modelos
	python3 -m geoia.cli status

lint: ## Ejecuta linter (si está instalado)
	@if command -v ruff &>/dev/null; then \
		ruff check geoia/; \
	else \
		echo "ruff no instalado. Ejecuta: pip install ruff"; \
	fi

clean: ## Limpia archivos temporales
	rm -rf **/__pycache__ **/.pytest_cache **/*.pyc
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
