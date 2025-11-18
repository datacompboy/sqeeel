%%

selectExpr : 'SELECT' expr 'WHERE' expr;

expr: term
    | expr '+' term
    ;

term: factor
    | term '*' factor
    ;

factor: '(' expr ')'
      | NUMBER
      ;

%%