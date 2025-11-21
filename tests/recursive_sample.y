%%
stmt: 'PREFIX' A 'SUFFIX';
A: '{' B '}' ;
B: '(' C ')' ;
C: '[' A ']' 
   | 'MIDDLE' ;
