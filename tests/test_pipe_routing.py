from openwebui_scanntech_function import Pipe


def test_excel_routing():
    pipe = Pipe()
    assert pipe._is_excel_request("gere o arquivo em excel pra mim")
    assert pipe._is_excel_request("planilha dos top 20 clientes")


def test_chart_routing():
    pipe = Pipe()
    assert pipe._is_chart_request("me mostra isso em um grafico")


def test_data_routing():
    pipe = Pipe()
    assert pipe._looks_like_data_question("top 20 produtos mais vendidos") is True
    assert pipe._looks_like_data_question("voce tem acesso a base da scanntech") is False
    assert pipe._looks_like_data_question("como funciona o scanntech analyst") is False
