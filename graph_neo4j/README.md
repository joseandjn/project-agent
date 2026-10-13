# Grafo de catalogo (Neo4j) — experimento aislado

Modela `data/catalogo/alimentos.json` como grafo para explorar relaciones entre
productos, especie, etapa de vida, tamano de raza, proteina, tipo de alimento e
ingredientes. El agente no lo usa directamente; el servicio `neo4j` ahora tambien guarda las
guias nutricionales por tienda (`app/nutricion/`), que comparten los nodos `Especie`, `Etapa`
e `Ingrediente`. Por eso recargar el catalogo solo borra productos y nodos huerfanos.

## Modelo

```
(:Producto)-[:PARA_ESPECIE]->(:Especie)         # Perro, Gato
(:Producto)-[:PARA_ETAPA]->(:Etapa)              # Cachorro, Adulto, Senior, Todas las edades
(:Producto)-[:PARA_TAMANO]->(:TamanoRaza)        # Pequeña, Grande, Todas las razas
(:Producto)-[:PROTEINA_PRINCIPAL]->(:Proteina)   # Pollo, Res, Salmón, Cordero, Pavo, Pato
(:Producto)-[:ES_TIPO]->(:TipoAlimento)          # Diario, Medicado
(:Producto)-[:CONTIENE]->(:Ingrediente)
```

## Uso

```bash
# 1. Levantar solo Neo4j (no toca postgres/redis/ollama/api)
docker compose up -d neo4j

# 2. Instalar el driver si no esta en el venv activo
pip install -r requirements.txt

# 3. Cargar el catalogo (borra y recarga el grafo)
python -m graph_neo4j.load_catalogo

# 4. Correr las consultas de ejemplo
python -m graph_neo4j.queries
```

Explorar visualmente en Neo4j Browser: http://localhost:7474 (usuario/clave en
`NEO4J_USER` / `NEO4J_PASSWORD` del `.env`, por defecto `neo4j` / `vethis1234`).

Consulta de ejemplo directa en el Browser:

```cypher
MATCH (p:Producto)-[:PARA_ESPECIE]->(:Especie {nombre: "Gato"}) RETURN p LIMIT 25
```

## Apagar

```bash
docker compose stop neo4j       # conserva los datos en el volumen neo4j_data
docker compose down -v neo4j    # o borra tambien el volumen
```
