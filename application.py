# application.py
"""
Arquivo de entrada para AWS Elastic Beanstalk
AWS procura especificamente por uma variável chamada 'application'
"""

from run import app

# AWS Elastic Beanstalk vai procurar por esta variável:
application = app

if __name__ == '__main__':
    # Para testes locais (opcional)
    application.run(debug=False, host='0.0.0.0', port=8080)