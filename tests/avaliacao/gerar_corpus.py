# SPDX-License-Identifier: GPL-3.0-or-later
"""Gera uma pasta «Bagunça» realista para avaliar a organização (com e sem IA).

Todos os documentos são fictícios: pessoas, empresas, números e moradas foram inventados
só para estes testes. Uso: python3 gerar_corpus.py <pasta-destino> [--validacao]
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------- documentos

# nome do ficheiro -> (áreas aceitáveis, linhas de texto)
DOCUMENTOS: dict[str, tuple[list[str], list[str]]] = {
    "scan_001.pdf": (["Finanças"], [
        "LusoEnergia, S.A.   NIF 509 876 543",
        "FATURA N.º FT 2025/184532   Data de emissão: 12-03-2025",
        "Cliente: Ana Ribeiro   NIF 234 567 890",
        "Morada de fornecimento: Rua das Flores, 12, 9990-100 Vila Exemplo",
        "CPE: PT 0002 0000 1234 5678 AB",
        "Período de faturação: 01-02-2025 a 28-02-2025",
        "Energia ativa simples: 245 kWh x 0,1589 EUR = 38,93 EUR",
        "Potência contratada 6,9 kVA: 9,87 EUR",
        "IVA (6% e 23%): 8,12 EUR",
        "TOTAL A PAGAR: 59,77 EUR   Data limite de pagamento: 02-04-2025",
        "Referência Multibanco: Entidade 21312  Referência 123 456 789",
        "ATCUD: JFX7K9P2-184532",
    ]),
    "Fatura Telecom Atlântico março.pdf": (["Finanças"], [
        "Telecom Atlântico, S.A.   NIF 502 345 678",
        "Fatura n.º TA2025/0098765   Data: 05-03-2025",
        "Cliente n.º 7788990   Ana Ribeiro",
        "Pacote Fibra 500 Mb + TV + telemóvel: 54,99 EUR",
        "Chamadas fora do pacote: 1,20 EUR",
        "Total a pagar: 56,19 EUR   Débito direto em 20-03-2025",
    ]),
    "doc20250131.pdf": (["Finanças"], [
        "Construções Oeste, Lda.   NIF 507 111 222",
        "RECIBO DE VENCIMENTO   Janeiro de 2025",
        "Trabalhador: João Martins   N.º Segurança Social: 12345678901",
        "Categoria: Técnico Administrativo",
        "Vencimento base: 1.250,00 EUR",
        "Subsídio de alimentação (22 dias x 6,00): 132,00 EUR",
        "Retenção na fonte IRS (11,2%): -140,00 EUR",
        "Segurança Social (11%): -137,50 EUR",
        "Líquido a receber: 1.104,50 EUR",
        "Transferência para IBAN PT50 0035 0000 1234 5678 9012 3",
    ]),
    "8f3a2c9d1e7b.pdf": (["Finanças"], [
        "AUTORIDADE TRIBUTÁRIA E ADUANEIRA",
        "DEMONSTRAÇÃO DE LIQUIDAÇÃO DE IRS   Ano dos rendimentos: 2024",
        "Identificação do documento: 2025 5001234567",
        "Sujeito passivo A: 234 567 890",
        "Rendimento global: 21.430,00 EUR",
        "Coleta líquida: 2.315,40 EUR",
        "Retenções na fonte: 2.940,00 EUR",
        "Valor a reembolsar: 624,60 EUR",
        "Data da liquidação: 2025-05-14",
    ]),
    "extrato.pdf": (["Finanças"], [
        "Banco Douro, S.A.",
        "Extrato da conta à ordem n.º 0045 1234 5678   Período: fevereiro de 2025",
        "IBAN PT50 0045 0000 1234 5678 9012 3   Titular: Ana Ribeiro",
        "Saldo inicial: 2.430,15 EUR",
        "03-02 Transferência recebida - Atlântida Seguros   +3.800,00",
        "05-02 Pagamento de serviços LusoEnergia   -59,77",
        "10-02 Compra com cartão Supermercado Oeste   -84,32",
        "Saldo final disponível: 6.086,06 EUR",
    ]),
    "Documento (1).docx": (["Saúde"], [
        "Clínica Santa Luzia - Laboratório de Análises Clínicas",
        "Utente: Ana Ribeiro   Data de colheita: 2025-02-20",
        "HEMOGRAMA COMPLETO",
        "Eritrócitos 4,6 x10^12/L (valores de referência 4,0 - 5,5)",
        "Hemoglobina 13,8 g/dL (12,0 - 16,0)",
        "BIOQUÍMICA: Glicose em jejum 92 mg/dL; Colesterol total 212 mg/dL",
        "Validado por: Dra. Marta Costa, especialista em Patologia Clínica",
    ]),
    "Receita.pdf": (["Saúde"], [
        "Serviço Nacional de Saúde - Receita Médica",
        "Receita n.º 1011 0000 1234 5678 901   Data: 2025-03-03",
        "Utente: João Martins   N.º de utente 123456789",
        "Unidade: Centro de Saúde de Vila Exemplo",
        "Medicamento (DCI): Amoxicilina + Ácido clavulânico 875 mg + 125 mg",
        "Posologia: 1 comprimido de 12 em 12 horas durante 8 dias",
        "Médico: Dra. Inês Almeida   Cédula profissional 54321",
    ]),
    "relatorio.pdf": (["Saúde"], [
        "Hospital do Oeste - Serviço de Ortopedia",
        "RELATÓRIO MÉDICO",
        "Doente: Ana Ribeiro   Processo n.º 778899   Data: 2025-01-15",
        "Motivo da consulta: dor no joelho direito após queda.",
        "Ressonância magnética: rotura parcial do menisco interno.",
        "Plano: fisioterapia durante 6 semanas e reavaliação em consulta.",
        "Dr. Ricardo Lopes, Ortopedista",
    ]),
    "Contrato.pdf": (["Casa"], [
        "CONTRATO DE ARRENDAMENTO PARA HABITAÇÃO COM PRAZO CERTO",
        "PRIMEIRO OUTORGANTE (Senhorio): Manuel Pereira, NIF 198 765 432",
        "SEGUNDO OUTORGANTE (Arrendatário): Ana Ribeiro, NIF 234 567 890",
        "Cláusula Primeira: O Senhorio dá de arrendamento a fração autónoma B",
        "do prédio sito na Rua do Carmo, 45, 9990-200 Vila Exemplo.",
        "Cláusula Segunda: início em 1 de março de 2025, pelo prazo de 3 anos.",
        "Cláusula Terceira: a renda mensal é de 650,00 EUR.",
        "Vila Exemplo, 20 de fevereiro de 2025",
    ]),
    "ata.pdf": (["Casa"], [
        "ATA N.º 27",
        "Aos dez dias do mês de março de 2025 reuniu a Assembleia de Condóminos",
        "do prédio sito na Rua do Carmo, 45, Vila Exemplo, com a ordem de trabalhos:",
        "1. Aprovação das contas do condomínio de 2024;",
        "2. Orçamento para 2025 e valor das quotas;",
        "3. Obras de impermeabilização da cobertura.",
        "A administração do condomínio apresentou as contas, aprovadas por unanimidade.",
    ]),
    "orcamento_obras.pdf": (["Casa"], [
        "Remodelações Oeste, Lda.   Orçamento n.º 2025/031",
        "Cliente: Ana Ribeiro   Obra: remodelação da casa de banho",
        "Demolição de azulejos e loiças: 450,00 EUR",
        "Canalização nova (água quente e fria): 780,00 EUR",
        "Aplicação de azulejo e pavimento: 1.200,00 EUR",
        "Total sem IVA: 2.430,00 EUR   Validade do orçamento: 30 dias",
    ]),
    "contrato_trabalho_assinado.pdf": (["Trabalho"], [
        "CONTRATO DE TRABALHO A TERMO CERTO",
        "Entre Construções Oeste, Lda., NIF 507 111 222, Entidade Empregadora,",
        "e João Martins, NIF 245 678 901, Trabalhador,",
        "é celebrado o presente contrato de trabalho, com as cláusulas seguintes:",
        "1.ª O Trabalhador é admitido para exercer funções de Técnico Administrativo.",
        "2.ª O período experimental é de 30 dias.",
        "3.ª A retribuição mensal ilíquida é de 1.250,00 EUR.",
    ]),
    "Proposta Cliente Atlântida.docx": (["Trabalho"], [
        "Proposta de Prestação de Serviços",
        "Cliente: Atlântida Seguros, S.A.",
        "Âmbito: acompanhamento como Product Owner na equipa de canais digitais,",
        "com gestão do backlog do produto, refinamento de user stories e sprint reviews.",
        "Duração: 6 meses, a partir de 1 de maio de 2025.",
        "Honorários: 3.800,00 EUR por mês, acrescidos de IVA à taxa legal.",
    ]),
    "notas reuniao.txt": (["Trabalho"], [
        "Reunião de acompanhamento do projeto Portal do Cliente - 2025-03-18",
        "Participantes: Ana Ribeiro (PO), Rui Silva (Scrum Master), equipa de desenvolvimento",
        "Pontos discutidos:",
        "- Estado do sprint 14: 21 de 26 pontos concluídos",
        "- Bloqueio na integração com o sistema de pagamentos",
        "- Prioridades do backlog para o sprint 15",
        "Ações: o Rui marca reunião com a equipa de pagamentos até sexta-feira.",
    ]),
    "Sprint Review Q1.pptx": (["Trabalho"], [
        "Sprint Review - Portal do Cliente",
        "Objetivo do sprint 14: novo fluxo de registo",
        "Resultados: 21 pontos entregues; conversão do registo +12%",
        "Próximos passos: integração com pagamentos e testes com utilizadores",
    ]),
    "certificado.pdf": (["Educação"], [
        "INSTITUTO DO EMPREGO E FORMAÇÃO PROFISSIONAL, I.P.",
        "CERTIFICADO DE FORMAÇÃO PROFISSIONAL",
        "Certifica-se que Ana Ribeiro concluiu com aproveitamento a ação de formação",
        "UFCD 0349 - Ambiente, segurança, higiene e saúde no trabalho,",
        "com a duração de 25 horas, realizada entre 10 e 21 de fevereiro de 2025.",
        "Classificação final: 17 valores.",
    ]),
    "Manual_Formando_UFCD_0349.pdf": (["Educação"], [
        "MANUAL DO FORMANDO",
        "UFCD 0349 - Ambiente, segurança, higiene e saúde no trabalho",
        "Objetivos: identificar os riscos profissionais e as medidas de prevenção.",
        "Módulo 1 - Conceitos de segurança e saúde no trabalho",
        "Módulo 2 - Riscos físicos, químicos e biológicos",
        "Módulo 3 - Equipamentos de proteção individual",
        "Exercícios de avaliação no final de cada módulo.",
    ]),
    "apontamentos gestao.docx": (["Educação"], [
        "Gestão de Projetos - Apontamentos da aula 5",
        "Capítulo 3: Planeamento e controlo",
        "O caminho crítico é a sequência de atividades com folga nula.",
        "Exercício: calcular a duração mínima do projeto a partir da rede de atividades.",
        "Para o teste: rever o método PERT e os diagramas de Gantt.",
    ]),
    "CV_2025.docx": (["Pessoal"], [
        "Curriculum Vitae",
        "Ana Ribeiro",
        "Experiência profissional",
        "2019 - atual: Product Owner sénior, consultora independente",
        "2014 - 2019: Analista funcional, Banco Douro",
        "Habilitações literárias: Mestrado em Gestão de Sistemas de Informação",
        "Competências: Scrum, Kanban, gestão de backlog, formação de adultos",
    ]),
    "carta.docx": (["Pessoal", "Trabalho"], [
        "Exmos. Senhores,",
        "Venho por este meio apresentar a minha candidatura à vaga de Product Owner",
        "publicada no vosso sítio na internet. Tenho mais de dez anos de experiência",
        "em equipas que trabalham com Scrum e Kanban, na banca e nos seguros.",
        "Junto envio o meu curriculum vitae e fico disponível para uma entrevista.",
        "Com os melhores cumprimentos,",
        "Ana Ribeiro",
    ]),
    "CC_frente_verso.pdf": (["Pessoal"], [
        "REPÚBLICA PORTUGUESA   CARTÃO DE CIDADÃO",
        "Apelido(s): RIBEIRO   Nome(s): ANA",
        "Sexo: F   Altura: 1,65   Nacionalidade: PRT   Data de nascimento: 14 03 1985",
        "N.º documento: 12345678 9 ZX1   Data de validade: 20 06 2031",
        "N.º de identificação fiscal: 234567890",
        "N.º de utente de saúde: 123456789",
    ]),
    "procuracao.pdf": (["Jurídico"], [
        "PROCURAÇÃO",
        "Ana Ribeiro, NIF 234 567 890, residente na Rua do Carmo, 45, Vila Exemplo,",
        "constitui seu bastante procurador João Martins, NIF 245 678 901,",
        "a quem confere os poderes necessários para a representar junto do",
        "Serviço de Finanças e de quaisquer repartições públicas.",
        "Vila Exemplo, 5 de março de 2025",
        "Reconhecimento de assinatura efetuado no Cartório Notarial de Vila Exemplo.",
    ]),
    "notificacao_tribunal.pdf": (["Jurídico"], [
        "TRIBUNAL JUDICIAL DA COMARCA DE LISBOA NORTE",
        "Juízo Local Cível de Torres Vedras   Processo n.º 1234/25.0T8TVD",
        "CITAÇÃO",
        "Fica V. Ex.ª citada para, no prazo de 30 dias, contestar a ação declarativa",
        "de condenação que lhe move Credifácil, S.A., com a advertência de que a falta",
        "de contestação importa a confissão dos factos articulados pelo autor.",
    ]),
    "inspecao.pdf": (["Veículos"], [
        "CENTRO DE INSPEÇÕES AUTO OESTE",
        "FICHA DE INSPEÇÃO PERIÓDICA",
        "Matrícula: 12-AB-34   Marca: Renault   Modelo: Clio",
        "Data da inspeção: 2025-02-10   Quilómetros: 98.450",
        "Resultado: APROVADO",
        "Próxima inspeção até: 2026-02-10",
    ]),
    "seguro_carro.pdf": (["Veículos", "Finanças"], [
        "CERTIFICADO INTERNACIONAL DE SEGURO AUTOMÓVEL (CARTA VERDE)",
        "Seguradora: Atlântida Seguros, S.A.   Apólice n.º 0045 1234 5678",
        "Tomador do seguro: Ana Ribeiro",
        "Veículo: Renault Clio, matrícula 12-AB-34",
        "Período de validade: 01-01-2025 a 31-12-2025",
        "Cobertura: responsabilidade civil obrigatória e danos próprios",
    ]),
    "boarding_pass.pdf": (["Viagens"], [
        "AeroLusa - Cartão de embarque / Boarding pass",
        "Passageiro: RIBEIRO/ANA MS",
        "Voo: AL1234   De: Lisboa (LIS)   Para: Funchal (FNC)",
        "Data: 22 de abril de 2025   Embarque: 08:15   Porta: 14   Lugar: 17C",
        "Reserva: X7KQ2P",
    ]),
    "booking_confirmation.pdf": (["Viagens"], [
        "Confirmação de reserva n.º 4455667788",
        "Hotel Ria Formosa, Tavira",
        "Check-in: 14 de agosto de 2025, a partir das 15:00",
        "Check-out: 21 de agosto de 2025, até às 11:00",
        "Quarto duplo com vista mar, pequeno-almoço incluído",
        "Hóspede: Ana Ribeiro   Total: 1.120,00 EUR, pago na reserva",
    ]),
    "manual.pdf": (["Compras e Garantias", "Casa"], [
        "Máquina de lavar roupa Eletrolar WM-8140",
        "Manual de instruções",
        "Leia atentamente estas instruções de segurança antes de utilizar o aparelho.",
        "Instalação: retire os parafusos de transporte antes da primeira utilização.",
        "Programas: algodão, sintéticos, delicados, lã, rápido 15 minutos.",
        "Manutenção: limpe o filtro da bomba de escoamento todos os meses.",
    ]),
    "garantia_portatil.pdf": (["Compras e Garantias"], [
        "Eletrolar - Certificado de garantia",
        "Produto: computador portátil Nexus 15, n.º de série NX15-2025-00871",
        "Data de compra: 2025-01-08   Loja: Eletrolar Torres Vedras",
        "Prazo de garantia: 3 anos a contar da data de compra.",
        "Guarde este certificado juntamente com a fatura de compra.",
    ]),
    "encomenda.eml": (["Compras e Garantias"], [
        "From: Compras Já <encomendas@comprasja.example>",
        "To: ana.ribeiro@example.com",
        "Subject: A sua encomenda n.º 402-1234567 foi enviada",
        "Date: Mon, 10 Mar 2025 09:12:00 +0000",
        "",
        "Olá Ana,",
        "A sua encomenda n.º 402-1234567 já foi enviada e chega dentro de 2 dias úteis.",
        "Artigos: auriculares sem fios (1 unidade) - 49,90 EUR",
        "Número de seguimento: EA123456789PT",
        "Obrigado por comprar connosco.",
    ]),
    "receita_bacalhau.docx": (["Lazer", "Outros"], [
        "Bacalhau à Brás",
        "Ingredientes (4 pessoas): 400 g de bacalhau demolhado, 500 g de batata palha,",
        "6 ovos, 2 cebolas, 2 dentes de alho, azeite, salsa e azeitonas pretas.",
        "Modo de preparação: aloure a cebola e o alho em azeite, junte o bacalhau",
        "desfiado e deixe cozinhar. Junte a batata palha e os ovos batidos.",
        "Sirva com salsa picada e azeitonas.",
    ]),
    "livro.pdf": (["Livros e Leituras"], [
        "O Mar e a Memória - romance",
        "Autora: Teresa Valente",
        "ISBN 978-972-0-04567-8   1.ª edição, 2021",
        "Todos os direitos reservados.",
        "Capítulo 1",
        "Naquela manhã de nevoeiro, o barco de pesca não regressou ao porto.",
    ]),
    "carta_banco.pdf": (["Finanças"], [
        "Banco Douro, S.A.",
        "Exma. Senhora Ana Ribeiro",
        "Rua do Carmo, 45, 9990-200 Vila Exemplo",
        "Assunto: alteração das condições do seu cartão de crédito",
        "Informamos que, a partir de 1 de maio de 2025, a taxa anual nominal",
        "do seu cartão de crédito passa a ser de 15,9%.",
        "Com os melhores cumprimentos, Banco Douro",
    ]),
    "digitalizacao_0007.pdf": (["Outros"], ["1"]),
    "Untitled.txt": (["Casa", "Outros"], [
        "Ligar ao canalizador amanhã de manhã por causa da fuga na cozinha.",
    ]),
    "Nova pasta/recibo_agua.txt": (["Finanças"], [
        "Águas do Oeste - Fatura n.º AO/2025/55123   Data: 02-03-2025",
        "Consumo de água: 9 m3   Saneamento e resíduos incluídos",
        "Total a pagar: 18,50 EUR",
    ]),
}


# Conjunto de validação: documentos diferentes, com as áreas esperadas fixadas antes de qualquer
# avaliação. Não serve para afinar palavras-chave nem pedidos à IA; mede a qualidade real.
VALIDACAO: dict[str, tuple[list[str], list[str]]] = {
    "fatura-recibo_0042.pdf": (["Finanças", "Trabalho"], [
        "Portal das Finanças - Fatura-Recibo n.º FR ATSIRE01FR/42",
        "Transmitente: Ana Ribeiro   NIF 234 567 890",
        "Adquirente: Atlântida Seguros, S.A.   NIF 503 222 111",
        "Descrição: prestação de serviços de consultoria em gestão de produto",
        "Valor base: 3.800,00 EUR   IVA 23%: 874,00 EUR",
        "Retenção na fonte de IRS (25%): 950,00 EUR   Importância recebida: 3.724,00 EUR",
    ]),
    "simulacao_credito.pdf": (["Finanças"], [
        "Banco Douro - Simulação de crédito à habitação",
        "Montante: 180.000 EUR   Prazo: 35 anos   Taxa variável Euribor 12 meses + 0,85%",
        "Prestação mensal estimada: 742,18 EUR   TAEG: 4,1%",
        "Esta simulação não constitui proposta contratual.",
    ]),
    "iuc_2025.pdf": (["Finanças", "Veículos"], [
        "AUTORIDADE TRIBUTÁRIA E ADUANEIRA",
        "Imposto Único de Circulação - Documento de cobrança",
        "Matrícula: 12-AB-34   Categoria B   Ano do imposto: 2025",
        "Valor a pagar: 152,30 EUR   Data limite: 30-04-2025",
    ]),
    "apolice_casa.pdf": (["Finanças", "Casa"], [
        "Atlântida Seguros - Seguro Multirriscos Habitação",
        "Condições particulares - Apólice n.º 0077 5512 3301",
        "Tomador do seguro: Ana Ribeiro   Local de risco: Rua do Carmo, 45, Vila Exemplo",
        "Capital seguro do edifício: 150.000 EUR   Recheio: 25.000 EUR",
        "Prémio anual: 218,40 EUR",
    ]),
    "marcacao.txt": (["Saúde"], [
        "Consulta de medicina dentária marcada para 14/11/2025 às 15h30, Clínica Sorriso Oeste.",
        "Traga o cartão de utente e chegue 10 minutos antes.",
    ]),
    "boletim_vacinas.pdf": (["Saúde"], [
        "Boletim Individual de Saúde - Registo de vacinação",
        "Utente: Ana Ribeiro",
        "Tétano e difteria (Td): 2019-05-02, reforço previsto em 2029",
        "Gripe sazonal: 2024-10-15   Lote FX1234",
    ]),
    "pauta_3periodo.pdf": (["Educação"], [
        "Escola Básica de Vila Exemplo - Ficha de avaliação do 3.º período",
        "Aluno: Tomás Ribeiro   Turma 6.º B",
        "Português: 5   Matemática: 4   Inglês: 5   Ciências Naturais: 4",
        "Observações da diretora de turma: aluno empenhado e participativo.",
    ]),
    "dissertacao_capitulo2.docx": (["Educação"], [
        "Capítulo 2 - Revisão da literatura",
        "Segundo Schwaber e Sutherland (2020), o Scrum é um enquadramento leve para equipas.",
        "Vários estudos empíricos apontam ganhos de previsibilidade com o Kanban.",
        "Referências bibliográficas",
        "Schwaber, K.; Sutherland, J. (2020). The Scrum Guide.",
    ]),
    "oferta_emprego.pdf": (["Trabalho", "Pessoal"], [
        "Carta-proposta de emprego",
        "Temos o prazer de lhe propor a função de Product Owner na nossa equipa de produto.",
        "Remuneração base anual: 48.000 EUR, paga em 14 prestações.",
        "Data de início prevista: 2 de janeiro de 2026.",
    ]),
    "timesheet_outubro.xlsx": (["Trabalho"], [
        "Registo de horas - outubro de 2025",
        "Cliente: Atlântida Seguros   Projeto: Portal do Cliente",
        "Dias trabalhados: 22   Total de horas: 176",
    ]),
    "agenda_reuniao.docx": (["Trabalho"], [
        "Convocatória - Reunião de direção de 20 de outubro de 2025",
        "Ordem de trabalhos:",
        "1. Orçamento para 2026",
        "2. Recrutamento para a equipa de dados",
        "3. Outros assuntos",
    ]),
    "bilhete_cp.pdf": (["Viagens"], [
        "CP - Comboios de Portugal",
        "Bilhete Intercidades: Lisboa Santa Apolónia - Porto Campanhã",
        "Data: 05-12-2025   Partida 09:09   Carruagem 3   Lugar 45",
    ]),
    "reserva_alojamento.eml": (["Viagens"], [
        "From: Reservas Gerês <reservas@casadolago.example>",
        "Subject: Reserva confirmada - Casa do Lago",
        "",
        "A sua estadia na Casa do Lago, Gerês, está confirmada: 3 noites, de 12 a 15 de junho.",
        "Check-in a partir das 16h. O anfitrião deixa a chave na caixa junto à porta.",
    ]),
    "fatura_telemovel_loja.pdf": (["Finanças", "Compras e Garantias"], [
        "Eletrolar - Fatura simplificada FS 2025/88123",
        "Smartphone Nova X 128 GB   349,99 EUR",
        "Pago com cartão. Garantia legal: 3 anos.",
    ]),
    "manual_tv.pdf": (["Compras e Garantias", "Casa"], [
        "Televisor LED 55 polegadas - Guia de início rápido",
        "1. Ligue o cabo de alimentação. 2. Insira as pilhas no comando.",
        "3. Siga o assistente para a sintonização automática dos canais.",
    ]),
    "matricula_escola.pdf": (["Educação", "Pessoal"], [
        "Pedido de matrícula no 1.º ano do ensino básico - ano letivo 2026/2027",
        "Aluno: Tomás Ribeiro   Encarregado de educação: Ana Ribeiro",
        "Estabelecimento pretendido: Escola Básica de Vila Exemplo",
    ]),
    "reparacao_carro.pdf": (["Veículos", "Finanças"], [
        "Auto Oeste, Lda. - Fatura n.º AO/2025/551",
        "Viatura: Renault Clio, matrícula 12-AB-34, 101.230 km",
        "Substituição de pastilhas de travão e discos dianteiros: 289,00 EUR",
        "Mão de obra: 60,00 EUR",
    ]),
    "multa.pdf": (["Veículos", "Jurídico"], [
        "Autoridade Nacional de Segurança Rodoviária",
        "Auto de contraordenação n.º 912345678",
        "Infração: excesso de velocidade (72 km/h numa via limitada a 50 km/h)",
        "Veículo: matrícula 12-AB-34   Coima: 120,00 EUR",
    ]),
    "contrato_ginasio.pdf": (["Lazer", "Outros", "Jurídico"], [
        "Ginásio Atlântico - Contrato de adesão",
        "Sócio: Ana Ribeiro   Plano: acesso livre a aulas de grupo e musculação",
        "Mensalidade: 35,00 EUR   Período de fidelização: 12 meses",
    ]),
    "arroz_pato.txt": (["Lazer", "Outros"], [
        "Arroz de pato à antiga",
        "Ingredientes: 1 pato, 300 g de arroz, 1 chouriço, 1 cebola, louro.",
        "Coza o pato, desfie a carne e leve ao forno com o arroz e rodelas de chouriço.",
    ]),
    "artigo_revista.pdf": (["Livros e Leituras", "Trabalho"], [
        "Revista Gestão Ágil n.º 12 - outubro de 2025",
        "Kanban para equipas de apoio ao cliente",
        "por Rui Silva",
        "Limitar o trabalho em curso é o primeiro passo para reduzir os tempos de resposta.",
    ]),
    "habilitacao_herdeiros.pdf": (["Jurídico"], [
        "Cartório Notarial de Vila Exemplo",
        "Escritura de habilitação de herdeiros",
        "Por óbito de Joaquim Ribeiro, ocorrido em 3 de março de 2025, sucederam-lhe",
        "como únicos herdeiros a cônjuge e os dois filhos.",
    ]),
    "lista_compras.txt": (["Outros", "Casa"], [
        "leite, pão, ovos, detergente da loiça, maçãs",
    ]),
    "scan_0091.pdf": (["Outros"], [""]),
    "anexo_b.pdf": (["Finanças"], [
        "Declaração de rendimentos IRS - Modelo 3 - Anexo B",
        "Rendimentos da categoria B - regime simplificado",
        "Prestações de serviços: 41.800,00 EUR",
    ]),
    "certidao_nascimento.pdf": (["Pessoal"], [
        "Conservatória do Registo Civil de Vila Exemplo",
        "Certidão de nascimento",
        "Nome: Tomás Ribeiro   Data de nascimento: 7 de setembro de 2019",
        "Filiação: Ana Ribeiro e João Martins",
    ]),
}


# --------------------------------------------------------------------------- formatos

def _pdf(path: Path, lines: list[str]) -> None:
    """PDF mínimo com texto (Helvetica, WinAnsi) que o pdftotext consegue ler."""
    ops = []
    y = 800
    for line in lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 10 Tf 40 {y} Td ({esc}) Tj ET")
        y -= 16
    stream = "\n".join(ops).encode("cp1252")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _docx(path: Path, lines: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{_xml_escape(t)}</w:t></w:r></w:p>" for t in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")


def _xlsx(path: Path, lines: list[str]) -> None:
    items = "".join(f"<si><t>{_xml_escape(t)}</t></si>" for t in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst>{items}</sst>")


def _pptx(path: Path, lines: list[str]) -> None:
    body = "".join(f"<a:p><a:r><a:t>{_xml_escape(t)}</a:t></a:r></a:p>" for t in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", f"<p:sld><p:txBody>{body}</p:txBody></p:sld>")


def _jpg(path: Path, color, date: str | None = None, camera: tuple[str, str] | None = None) -> None:
    from PIL import Image
    img = Image.new("RGB", (64, 48), color)
    exif = Image.Exif()
    if camera:
        exif[271], exif[272] = camera
    if date:
        exif[306] = date
    img.save(path, "JPEG", exif=exif.tobytes() if (camera or date) else b"")


def _png(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (32, 32), (30, 90, 200)).save(path, "PNG")


def _mp3(path: Path, artist: str, album: str, title: str) -> None:
    # 30 tramas MPEG-1 Layer III mudas (128 kbit/s, 44,1 kHz) com etiquetas ID3.
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * 30)
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3
        ID3().save(path)
        tags = EasyID3(path)
        tags["artist"], tags["album"], tags["title"] = artist, album, title
        tags.save()
    except ImportError:
        pass


def _escrever_documentos(root: Path, documentos: dict[str, tuple[list[str], list[str]]]) -> dict[str, list[str]]:
    esperado: dict[str, list[str]] = {}
    for rel, (areas, lines) in documentos.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        ext = path.suffix.lower()
        if ext == ".pdf":
            _pdf(path, lines)
        elif ext == ".docx":
            _docx(path, lines)
        elif ext == ".pptx":
            _pptx(path, lines)
        elif ext == ".xlsx":
            _xlsx(path, lines)
        else:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        esperado[rel] = areas
    return esperado


def gerar_validacao(dest: Path) -> dict[str, list[str]]:
    root = dest / "Bagunça"
    root.mkdir(parents=True, exist_ok=True)
    esperado = _escrever_documentos(root, VALIDACAO)
    (dest / "esperado.json").write_text(json.dumps(esperado, ensure_ascii=False, indent=2), encoding="utf-8")
    return esperado


def gerar(dest: Path) -> dict[str, list[str]]:
    root = dest / "Bagunça"
    root.mkdir(parents=True, exist_ok=True)
    esperado = _escrever_documentos(root, DOCUMENTOS)

    # Fotografias, capturas de ecrã e imagens recebidas
    _jpg(root / "IMG_20240812_101010.jpg", (200, 120, 60), "2024:08:12 10:10:10", ("Google", "Pixel 7"))
    _jpg(root / "IMG_20240813_093000.jpg", (190, 110, 70), "2024:08:13 09:30:00", ("Google", "Pixel 7"))
    _jpg(root / "PXL_20231224_201500.jpg", (20, 120, 60), "2023:12:24 20:15:00", ("Google", "Pixel 7"))
    _jpg(root / "IMG-20250301-WA0005.jpg", (90, 90, 90))
    _jpg(root / "IMG-20250302-WA0011.jpg", (95, 95, 95))
    _png(root / "Captura de ecrã de 2025-01-02 10-00-00.png")
    _png(root / "diagrama.png")
    (root / "Férias Algarve").mkdir(exist_ok=True)
    for i in range(1, 4):
        _jpg(root / "Férias Algarve" / f"praia{i}.jpg", (40, 140, 200 - i * 10),
             f"2024:08:{14 + i:02d} 11:00:00", ("Apple", "iPhone 13"))
    # Música
    _mp3(root / "musica1.mp3", "Madredeus", "O Espírito da Paz", "Ao longe o mar")
    _mp3(root / "faixa02.mp3", "Unknown Artist", "Unknown Album", "Track 02")
    # Outros tipos
    (root / "VID_20240812_120000.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    (root / "programa.deb").write_bytes(b"!<arch>\n")
    (root / "setup.exe").write_bytes(b"MZ" + b"\x00" * 64)
    (root / "fotos.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (root / "script_backup.sh").write_text("#!/bin/sh\nrsync -a ~/Documentos /media/backup\n", encoding="utf-8")
    (root / "pagina_guardada.html").write_text(
        "<html><head><title>Simulador de IRS 2025</title></head><body>"
        "<h1>Simulador de IRS</h1><p>Rendimento coletável e taxa de imposto.</p></body></html>",
        encoding="utf-8")
    (root / "Thumbs.db").write_bytes(b"junk")
    (root / "Pasta vazia").mkdir(exist_ok=True)
    (dest / "esperado.json").write_text(json.dumps(esperado, ensure_ascii=False, indent=2), encoding="utf-8")
    return esperado


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    out = Path(args[0])
    if "--validacao" in sys.argv:
        gerar_validacao(out)
    else:
        gerar(out)
    n = sum(1 for _ in (out / "Bagunça").rglob("*") if _.is_file())
    print(f"Corpus criado em {out / 'Bagunça'} ({n} ficheiros).")
