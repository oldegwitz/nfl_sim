# nfl_sim — motor jugada a jugada (Bloque 2)

- Especificación y criterios: contexto_proyecto_nfl.md, sección 6b (proyecto NFL Secret LAB).
- Lee ~/nfl_ev/historico/ y las capturas del bot **sin escribir en ellas**.
- 10.000 simulaciones en paralelo; nada de bucles por simulación o por juego. `sprint2.py` es s2-v1 congelado (md5 `baad72c6…`): cambiarlo anula la confirmación 31A.
- datos/, salidas/, respaldos/, credenciales/ y semana.ini no entran a Git (lista blanca en `.gitignore`, anclada en la raíz). Las credenciales nunca entran a Git.

## Dónde corre (decisión 70, 10-nov-2026)
- EC2 compartida (NFL, Traccar, Bot Binance, IC). NFL vive en el usuario **`nflbot`** (sin sudo): `/home/nflbot/nfl_sim` y `/home/nflbot/nfl_ev`, cada uno con su venv (`requirements-lock.txt`).
- Servicios = unidades de **usuario** (`systemctl --user`, con linger): `nfl-ev-bot`, `nfl-sim-orden`, `nfl-sim-semana` + `.timer`. Sus archivos están en `systemd/` (y `~/nfl_ev/systemd/`); se editan aquí y se instalan con `instalar_servicios.sh unidades`.
- Topes (10-nov, «igual que Bot Binance»): todo NFL ≤ 1,5 GiB (MemoryHigh 1380M) y 1 vCPU con el mismo peso de CPU (slice `user-<uid>.slice`, lo pone el administrador); bot 350 MB; motor y bot de órdenes 1200M cada uno, sin swap; nice 10. Lo pesado (estudios, s3) va a la EC2 a demanda (70c, fase D).
- El código llega **solo con `git pull`** desde GitHub (llave de despliegue de solo lectura, alias `github-nfl_sim`): `bash ~/nfl_sim/actualizar.sh`. En la EC2 no se edita código ni se hacen commits.
- Scripts: `instalar_servicios.sh` (venvs, unidades, arrancar, prueba), `migrar_datos.sh` (paso B3, una sola vez, con sudo), `actualizar.sh` (cada cambio de código: lo prueba aparte con `git worktree` antes de pasarlo), `pico_memoria.sh` (cada corrida real deja su pico de memoria en semana.log), `cargar_*.sh` (secretos con entrada oculta).
- Ojo: `nfl_ev_bot.py prueba` (congelado) mira la unidad del SISTEMA para saber si el bot corre; ahora es de usuario, así que esa guarda ya no avisa. No correr `nfl_ev_bot.py prueba` ni `diagnostico` con `nfl-ev-bot` activo (`systemctl --user is-active nfl-ev-bot`).
