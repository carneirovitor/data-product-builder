# Produto de dados — corridas de táxi NYC

**Idioma:** [English](business_questions.md) · **Português**

## Objetivo

Ingerir registros de corridas de táxi de Nova York em um data lake, disponibilizá-los para consumo analítico e responder a perguntas de negócio sobre preço e ocupação da frota — com qualidade e governança auditáveis.

Escopo deste produto:

- Ingestão dos arquivos TLC (yellow e green) no lake
- Camada de consumo consultável (SQL)
- Duas análises de negócio materializadas como KPIs

---

## Dados

Fonte: [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).

Recorte: **janeiro a maio de 2023** (yellow + green). Dicionários e metadados de apoio estão em `files/`.

---

## Considerações de modelagem

- Landing dos arquivos originais (Volume / object store)
- Camada de consumo estruturada para o usuário final
- Limpeza e regras de qualidade conforme a política do domínio
- Na camada de consumo devem existir, no mínimo: **VendorID**, **passenger_count**, **total_amount**, **tpep_pickup_datetime**, **tpep_dropoff_datetime**
- Demais colunas são opcionais; o lake parte sem tabelas pré-existentes

---

## Perguntas de negócio

1. Qual a média de valor total (`total_amount`) recebido em um mês, considerando todos os yellow táxis da frota?
2. Qual a média de passageiros (`passenger_count`) por cada hora do dia, no mês de maio, considerando todos os táxis da frota?

Respostas materializadas: `consumption.kpi_*` (ver README).
