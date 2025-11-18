%{
#include <stdio.h>
%}

%token NUMBER
%left '+' '-'
%left '*' '/'
%nonassoc UMINUS

%%

/* This is a comment */
stmt : expr ';' { printf("result: %d\n", $1); }
     | /* empty */
     ;

expr : expr '+' term { $$ = $1 + $3; }
     | expr '-' term %prec UMINUS { $$ = $1 - $3; }
     | term
     

term : term '*' factor { $$ = $1 * $3; }
     | factor

factor : '(' expr ')'
       | NUMBER
       ;

%%

int main() { return 0; }