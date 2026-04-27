from pine2ast.lexer.token import TokenKind

PRECEDENCE = {
    TokenKind.OR: 10,
    TokenKind.AND: 20,
    TokenKind.EQEQ: 30,
    TokenKind.NEQ: 30,
    TokenKind.LT: 40,
    TokenKind.LTE: 40,
    TokenKind.GT: 40,
    TokenKind.GTE: 40,
    TokenKind.PLUS: 50,
    TokenKind.MINUS: 50,
    TokenKind.STAR: 60,
    TokenKind.SLASH: 60,
    TokenKind.PERCENT: 60,
}
