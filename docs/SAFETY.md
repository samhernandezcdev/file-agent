1. El sistema nunca elimina archivos automáticamente.

2. Durante Milestone 0 no puede mover ni renombrar archivos.

3. El sistema solo puede leer dentro de sandbox/.

4. Toda futura modificación del filesystem deberá pasar por un TransactionEngine.

5. Ningún LLM tendrá acceso directo a operaciones destructivas.

6. confidence != permission.

7. Toda acción futura deberá poder auditarse y revertirse.