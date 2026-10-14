
import os
import sqlite3
import secrets
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.environ.get(
    "AGENDA_SECRET_KEY",
    "CAMBIAR-ESTA-CLAVE-POR-UNA-LARGA-Y-PRIVADA"
)

APP_ENV = os.environ.get("APP_ENV", "development")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(APP_ENV == "production"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4)
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turnos.db")
MINUTOS_PARA_PAGAR = 30
HORARIOS = ["10:00", "12:30", "15:00", "18:00"]


# --------------------------------------------------
# BASE DE DATOS
# --------------------------------------------------

def conectar():
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    return conexion


def preparar_base():
    conexion = conectar()
    try:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS turnos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL
            )
        """)

        columnas = {
            fila["name"]
            for fila in conexion.execute(
                "PRAGMA table_info(turnos)"
            ).fetchall()
        }

        if "estado_sena" not in columnas:
            conexion.execute("""
                ALTER TABLE turnos
                ADD COLUMN estado_sena TEXT NOT NULL DEFAULT 'pendiente'
            """)

        if "creado_en" not in columnas:
            conexion.execute("""
                ALTER TABLE turnos ADD COLUMN creado_en TEXT
            """)

        if "origen" not in columnas:
            conexion.execute("""
                ALTER TABLE turnos
                ADD COLUMN origen TEXT NOT NULL DEFAULT 'admin'
            """)

        if "estado_turno" not in columnas:
            conexion.execute("""
                ALTER TABLE turnos
                ADD COLUMN estado_turno TEXT NOT NULL DEFAULT 'reservado'
            """)

        conexion.execute("""
            CREATE INDEX IF NOT EXISTS indice_turnos_fecha_hora
            ON turnos(fecha, hora)
        """)

        # Configuración del administrador.
        # Solo se crea el usuario inicial si todavía no existe.
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS admin_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                usuario TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)

        administrador = conexion.execute("""
            SELECT id FROM admin_config WHERE id = 1
        """).fetchone()

        if administrador is None:
            conexion.execute("""
                INSERT INTO admin_config (id, usuario, password_hash)
                VALUES (1, ?, ?)
            """, (
                "karen",
                generate_password_hash("123")
            ))

        conexion.commit()
    finally:
        conexion.close()


def expirar_reservas():
    limite = (
        datetime.now() - timedelta(minutes=MINUTOS_PARA_PAGAR)
    ).isoformat(timespec="seconds")

    conexion = conectar()
    try:
        conexion.execute("""
            UPDATE turnos
            SET estado_turno = 'expirado'
            WHERE origen = 'publico'
              AND estado_sena = 'pendiente'
              AND estado_turno = 'reservado'
              AND creado_en IS NOT NULL
              AND creado_en <= ?
        """, (limite,))
        conexion.commit()
    finally:
        conexion.close()


preparar_base()


# --------------------------------------------------
# FECHAS Y FUNCIONES AUXILIARES
# --------------------------------------------------

def fecha_valida(fecha_texto):
    try:
        fecha_obj = datetime.strptime(
            fecha_texto, "%Y-%m-%d"
        ).date()
    except (ValueError, TypeError):
        return False

    return fecha_obj.weekday() in (2, 5) and fecha_obj >= date.today()


def fechas_disponibles(incluir=None):
    hoy = date.today()
    fechas = []

    for numero_dia in range(93):
        dia = hoy + timedelta(days=numero_dia)
        if dia.weekday() in (2, 5):
            fechas.append(dia.isoformat())

    if incluir:
        try:
            fecha_extra = datetime.strptime(
                incluir, "%Y-%m-%d"
            ).date()

            if fecha_extra.weekday() in (2, 5) and incluir not in fechas:
                fechas.append(incluir)
        except (ValueError, TypeError):
            pass

    return sorted(fechas)


def etiqueta_fecha(valor):
    try:
        dia = datetime.strptime(valor, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return valor

    dias = [
        "lunes", "martes", "miércoles", "jueves",
        "viernes", "sábado", "domingo"
    ]
    return f"{dias[dia.weekday()].capitalize()} {dia.strftime('%d/%m/%Y')}"


app.jinja_env.filters["etiqueta_fecha"] = etiqueta_fecha
app.jinja_env.filters["fecha_bonita"] = (
    lambda valor: datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")
    if valor else ""
)


def obtener_admin():
    conexion = conectar()
    try:
        return conexion.execute("""
            SELECT usuario, password_hash
            FROM admin_config WHERE id = 1
        """).fetchone()
    finally:
        conexion.close()


def usuario_admin():
    return session.get("es_admin") is True


def requiere_admin(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if not usuario_admin():
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)
    return envoltura


def horarios_disponibles(fecha_texto):
    expirar_reservas()

    if not fecha_valida(fecha_texto):
        return []

    conexion = conectar()
    try:
        ocupados = conexion.execute("""
            SELECT hora FROM turnos
            WHERE fecha = ? AND estado_turno = 'reservado'
        """, (fecha_texto,)).fetchall()

        horas_ocupadas = {fila["hora"] for fila in ocupados}
        return [hora for hora in HORARIOS if hora not in horas_ocupadas]
    finally:
        conexion.close()


# --------------------------------------------------
# ESTILOS
# --------------------------------------------------

ESTILOS = """
<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    padding: 20px;
    font-family: Arial, sans-serif;
    background: #111111;
    color: #f5f1e8;
}

.contenedor {
    max-width: 1050px;
    margin: 20px auto;
    background: #1c1c1c;
    color: #f5f1e8;
    padding: 25px;
    border: 1px solid #b99a52;
    border-radius: 16px;
    box-shadow: 0 8px 30px #00000066;
}

h1, h2 {
    color: #d4af62;
}

input, select, textarea {
    width: 100%;
    padding: 12px;
    margin: 7px 0 14px;
    border: 1px solid #8c7747;
    border-radius: 8px;
    font-size: 16px;
    background: #ffffff;
    color: #222222;
}

button, .boton {
    display: inline-block;
    width: auto;
    background: #c5a253;
    color: #111111;
    border: 1px solid #d9bd79;
    padding: 11px 16px;
    border-radius: 8px;
    text-decoration: none;
    cursor: pointer;
    font-weight: bold;
}

button:hover, .boton:hover {
    background: #e0c477;
}

button:disabled {
    opacity: .5;
    cursor: not-allowed;
}

.secundario {
    background: #444444;
    color: #ffffff;
}

.peligro {
    background: #b52e3c;
    color: #ffffff;
}

.ok {
    color: #75d6a0;
    font-weight: bold;
}

.pendiente {
    color: #e5bd62;
    font-weight: bold;
}

.aviso, .exito, .error {
    padding: 12px;
    border-radius: 8px;
    margin: 12px 0;
}

.aviso {
    background: #29251c;
    border: 1px solid #8c7747;
}

.exito {
    background: #173526;
    color: #b9f0ce;
}

.error {
    background: #3a2020;
    color: #ffd0d0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 15px;
    background: #1c1c1c;
    color: #f5f1e8;
}

th, td {
    padding: 10px;
    text-align: left;
    border-bottom: 1px solid #51462f;
}

th {
    background: #30291b;
    color: #e0c477;
}

form.inline {
    display: inline-block;
    margin: 0;
}

form.inline button {
    margin: 3px;
}

@media (max-width: 600px) {
    body {
        padding: 10px;
    }

    .contenedor {
        margin: 5px auto;
        padding: 16px;
    }

    table {
        display: block;
        overflow-x: auto;
    }
}
nav { margin-bottom: 20px; }
nav a { margin-right: 12px; }
.pequeno { font-size: 13px; color: #715c69; }
@media(max-width: 700px) {
    body { padding: 8px; }
    .contenedor { padding: 14px; margin: 5px auto; }
    table { font-size: 13px; }
    th, td { padding: 6px; }
    .tabla-scroll { overflow-x: auto; }
}
</style>
"""


# --------------------------------------------------
# AGENDA PUBLICA
# --------------------------------------------------

PAGINA_PUBLICA = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agenda de pestañas</title>
""" + ESTILOS + """
</head>
<body>
<div class="contenedor">
    <nav>
        <a class="boton secundario" href="{{ url_for('login') }}">Administración</a>
    </nav>

    <h1>Agenda de turnos para pestañas</h1>
    <p>Elegí una fecha y un horario disponible.</p>

    {% with mensajes = get_flashed_messages(with_categories=true) %}
      {% for categoria, mensaje in mensajes %}
        <div class="{{ 'error' if categoria == 'error' else 'exito' }}">{{ mensaje }}</div>
      {% endfor %}
    {% endwith %}

    <form method="GET" action="/">
        <label>Fecha de atención (miércoles o sábado)</label>
        <select name="fecha" required onchange="this.form.submit()">
            <option value="">Elegí una fecha</option>
            {% for fecha in fechas %}
                <option value="{{ fecha }}" {% if fecha == fecha_seleccionada %}selected{% endif %}>
                    {{ fecha|etiqueta_fecha }}
                </option>
            {% endfor %}
        </select>
        <noscript><button type="submit">Ver horarios</button></noscript>
    </form>

    <form method="POST" action="{{ url_for('reservar') }}">
        <label>Nombre y apellido</label>
        <input name="nombre" maxlength="100" required>
        <label>Teléfono</label>
        <input name="telefono" type="tel" maxlength="40" required>
        <input type="hidden" name="fecha" value="{{ fecha_seleccionada }}">

        <label>Horario disponible</label>
        <select name="hora" required>
            <option value="">Elegí un horario</option>
            {% for hora in horarios %}
                <option value="{{ hora }}">{{ hora }}</option>
            {% endfor %}
        </select>

        {% if fecha_seleccionada and not horarios %}
            <p class="aviso">No quedan horarios libres para esa fecha. Elegí otro miércoles o sábado.</p>
        {% elif not fecha_seleccionada %}
            <p class="aviso">Primero elegí una fecha para ver los horarios.</p>
        {% endif %}

        <button type="submit" {% if not horarios %}disabled{% endif %}>Solicitar turno</button>
    </form>

    <div class="aviso">
        <strong>Importante:</strong> la seña queda pendiente.
        El plazo de 30 minutos se comprueba cuando se utiliza la agenda.
        Consultá con el negocio cómo realizar la transferencia.
    </div>
    <p class="pequeno">La solicitud no verifica automáticamente el pago.</p>
</div>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def inicio():
    expirar_reservas()
    fecha_seleccionada = request.args.get("fecha", "")

    if not fecha_valida(fecha_seleccionada):
        fecha_seleccionada = ""

    return render_template_string(
        PAGINA_PUBLICA,
        fechas=fechas_disponibles(),
        fecha_seleccionada=fecha_seleccionada,
        horarios=horarios_disponibles(fecha_seleccionada) if fecha_seleccionada else []
    )


@app.route("/reservar", methods=["POST"])
def reservar():
    expirar_reservas()
    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    fecha_texto = request.form.get("fecha", "").strip()
    hora = request.form.get("hora", "").strip()

    if not nombre or not telefono or len(nombre) > 100 or len(telefono) > 40:
        flash("Completá correctamente el nombre y el teléfono.", "error")
        return redirect(url_for("inicio", fecha=fecha_texto))

    if not fecha_valida(fecha_texto):
        flash("Elegí una fecha futura válida: miércoles o sábado.", "error")
        return redirect(url_for("inicio"))

    if hora not in HORARIOS:
        flash("Elegí uno de los horarios disponibles.", "error")
        return redirect(url_for("inicio", fecha=fecha_texto))

    conexion = conectar()
    try:
        ocupada = conexion.execute("""
            SELECT id FROM turnos
            WHERE fecha = ? AND hora = ? AND estado_turno = 'reservado'
        """, (fecha_texto, hora)).fetchone()

        if ocupada:
            flash("Ese horario ya está ocupado. Elegí otro.", "error")
            return redirect(url_for("inicio", fecha=fecha_texto))

        conexion.execute("""
            INSERT INTO turnos
                (nombre, telefono, fecha, hora, estado_sena,
                 creado_en, origen, estado_turno)
            VALUES (?, ?, ?, ?, 'pendiente', ?, 'publico', 'reservado')
        """, (
            nombre, telefono, fecha_texto, hora,
            datetime.now().isoformat(timespec="seconds")
        ))
        conexion.commit()
    finally:
        conexion.close()

    return render_template_string("""
        <!doctype html><html lang="es"><head>
        <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Solicitud de turno</title>
        """ + ESTILOS + """
        </head><body><div class="contenedor">
        <h1>Solicitud de turno recibida</h1>
        <p>Hola, {{ nombre }}.</p>
        <h2>{{ fecha|fecha_bonita }} a las {{ hora }}</h2>
        <div class="aviso">La seña figura como pendiente. Comunicate con el negocio
        para recibir los datos de transferencia y confirmar el pago.</div>
        <a class="boton" href="{{ url_for('inicio') }}">Volver a la agenda</a>
        </div></body></html>
    """, nombre=nombre, fecha=fecha_texto, hora=hora)


# --------------------------------------------------
# INICIO DE SESION Y CAMBIO DE CONTRASEÑA
# --------------------------------------------------

PAGINA_LOGIN = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Administración</title>
""" + ESTILOS + """
</head>
<body>
<div class="contenedor" style="max-width:430px">
    <h1>Administración</h1>
    <p>Ingresá tu usuario y contraseña.</p>

    {% with mensajes = get_flashed_messages(with_categories=true) %}
      {% for categoria, mensaje in mensajes %}
        <div class="{{ 'error' if categoria == 'error' else 'exito' }}">{{ mensaje }}</div>
      {% endfor %}
    {% endwith %}

    <form method="POST">
        <label>Usuario</label>
        <input name="usuario" maxlength="100" required autofocus>
        <label>Contraseña</label>
        <input type="password" name="password" required>
        <button type="submit">Ingresar</button>
    </form>
    <a href="{{ url_for('inicio') }}">Volver a la agenda</a>
</div>
</body>
</html>
"""


@app.route("/admin", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if usuario_admin():
        return redirect(url_for("panel_admin"))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        admin = obtener_admin()

        usuario_correcto = (
            admin is not None
            and secrets.compare_digest(usuario, admin["usuario"])
        )
        password_correcta = (
            admin is not None
            and check_password_hash(admin["password_hash"], password)
        )

        if usuario_correcto and password_correcta:
            session.clear()
            session["es_admin"] = True
            session.permanent = True
            return redirect(url_for("panel_admin"))

        flash("Usuario o contraseña incorrectos.", "error")

    return render_template_string(PAGINA_LOGIN)


PAGINA_CAMBIAR_PASSWORD = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cambiar contraseña</title>
""" + ESTILOS + """
</head>
<body>
<div class="contenedor" style="max-width:520px">
    <h1>Cambiar contraseña</h1>
    <p>Usuario administrador: <strong>{{ usuario }}</strong></p>

    {% with mensajes = get_flashed_messages(with_categories=true) %}
      {% for categoria, mensaje in mensajes %}
        <div class="{{ 'error' if categoria == 'error' else 'exito' }}">{{ mensaje }}</div>
      {% endfor %}
    {% endwith %}

    <form method="POST">
        <label>Contraseña actual</label>
        <input type="password" name="actual" required>

        <label>Nueva contraseña (mínimo 8 caracteres)</label>
        <input type="password" name="nueva" minlength="8" required>

        <label>Repetí la nueva contraseña</label>
        <input type="password" name="confirmacion" minlength="8" required>

        <button type="submit">Guardar nueva contraseña</button>
    </form>
    <a class="boton secundario" href="{{ url_for('panel_admin') }}">Volver al panel</a>
</div>
</body>
</html>
"""


@app.route("/admin/cambiar-password", methods=["GET", "POST"])
@requiere_admin
def cambiar_password():
    admin = obtener_admin()

    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmacion = request.form.get("confirmacion", "")

        if not check_password_hash(admin["password_hash"], actual):
            flash("La contraseña actual no es correcta.", "error")
        elif len(nueva) < 8:
            flash("La nueva contraseña debe tener al menos 8 caracteres.", "error")
        elif nueva != confirmacion:
            flash("Las nuevas contraseñas no coinciden.", "error")
        elif nueva == actual:
            flash("Elegí una contraseña diferente de la actual.", "error")
        else:
            conexion = conectar()
            try:
                conexion.execute("""
                    UPDATE admin_config
                    SET password_hash = ?
                    WHERE id = 1
                """, (generate_password_hash(nueva),))
                conexion.commit()
            finally:
                conexion.close()

            flash("Contraseña cambiada correctamente.", "success")
            return redirect(url_for("panel_admin"))

    return render_template_string(
        PAGINA_CAMBIAR_PASSWORD,
        usuario=admin["usuario"]
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("inicio"))


# --------------------------------------------------
# PANEL DE ADMINISTRACION
# --------------------------------------------------

PLANTILLA_ADMIN = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de turnos</title>
""" + ESTILOS + """
</head>
<body>
<div class="contenedor">
    <h1>Panel de administración</h1>
    <nav>
        <a href="{{ url_for('panel_admin') }}">Ver turnos</a>
        <a href="{{ url_for('inicio') }}">Ver agenda pública</a>
        <a href="{{ url_for('cambiar_password') }}">Cambiar contraseña</a>
        <form class="inline" method="POST" action="{{ url_for('logout') }}">
            <button class="secundario" type="submit">Cerrar sesión</button>
        </form>
    </nav>

    {% with mensajes = get_flashed_messages(with_categories=true) %}
      {% for categoria, mensaje in mensajes %}
        <div class="{{ 'error' if categoria == 'error' else 'exito' }}">{{ mensaje }}</div>
      {% endfor %}
    {% endwith %}

    <h2>Buscar y filtrar turnos</h2>
    <form method="GET" action="{{ url_for('panel_admin') }}">
        <label>Nombre o teléfono</label>
        <input name="buscar" value="{{ buscar }}" placeholder="Nombre o teléfono">

        <label>Fecha</label>
        <select name="fecha">
            <option value="">Todas las fechas</option>
            {% for fecha in fechas %}
                <option value="{{ fecha }}" {% if fecha == fecha_filtro %}selected{% endif %}>
                    {{ fecha|etiqueta_fecha }}
                </option>
            {% endfor %}
        </select>

        <label>Estado de la seña</label>
        <select name="sena">
            <option value="">Todas las señas</option>
            <option value="pendiente" {% if sena_filtro == 'pendiente' %}selected{% endif %}>Pendientes</option>
            <option value="pagada" {% if sena_filtro == 'pagada' %}selected{% endif %}>Pagadas</option>
        </select>
        <button type="submit">Buscar</button>
        <a class="boton secundario" href="{{ url_for('panel_admin') }}">Limpiar</a>
    </form>

    <h2>Reservar manualmente</h2>
    <form method="POST" action="{{ url_for('admin_reservar') }}">
        <label>Nombre y apellido</label>
        <input name="nombre" maxlength="100" required>
        <label>Teléfono</label>
        <input name="telefono" maxlength="40" required>
        <label>Fecha</label>
        <select name="fecha" required>
            <option value="">Elegí una fecha</option>
            {% for fecha in fechas %}
                <option value="{{ fecha }}">{{ fecha|etiqueta_fecha }}</option>
            {% endfor %}
        </select>
        <label>Horario</label>
        <select name="hora" required>
            <option value="">Elegí un horario</option>
            {% for hora in todos_horarios %}
                <option value="{{ hora }}">{{ hora }}</option>
            {% endfor %}
        </select>
        <label>Estado de la seña</label>
        <select name="estado_sena">
            <option value="pendiente">Pendiente</option>
            <option value="pagada">Pagada</option>
        </select>
        <button type="submit">Guardar turno</button>
    </form>

    <h2>Turnos registrados ({{ turnos|length }})</h2>
    <div class="tabla-scroll">
    <table>
      <thead>
        <tr>
          <th>Fecha</th><th>Hora</th><th>Nombre</th><th>Teléfono</th>
          <th>Seña</th><th>Acciones</th>
        </tr>
      </thead>
      <tbody>
      {% for turno in turnos %}
        <tr>
          <td>{{ turno['fecha']|fecha_bonita }}</td>
          <td>{{ turno['hora'] }}</td>
          <td>{{ turno['nombre'] }}</td>
          <td>{{ turno['telefono'] }}</td>
          <td>
            {% if turno['estado_sena'] == 'pagada' %}
              <span class="ok">Pagada</span>
            {% else %}
              <span class="pendiente">Pendiente</span>
            {% endif %}
          </td>
          <td>
            <a class="boton secundario" href="{{ url_for('modificar_turno', turno_id=turno['id']) }}">Editar</a>

            {% if turno['estado_sena'] != 'pagada' %}
            <form class="inline" method="POST" action="{{ url_for('marcar_pagada', turno_id=turno['id']) }}"
                  onsubmit="return confirm('¿Confirmás que recibiste la seña?')">
              <button type="submit">Marcar pagada</button>
            </form>
            {% endif %}

            <form class="inline" method="POST" action="{{ url_for('cancelar_turno', turno_id=turno['id']) }}"
                  onsubmit="return confirm('¿Seguro que querés cancelar este turno?')">
              <button class="peligro" type="submit">Cancelar</button>
            </form>
          </td>
        </tr>
      {% else %}
        <tr><td colspan="6">No hay turnos que coincidan con la búsqueda.</td></tr>
      {% endfor %}
      </tbody>
    </table>
    </div>

    <p class="pequeno">Los turnos se guardan en la base de datos existente.
    El vencimiento se comprueba al utilizar la página.</p>
</div>
</body>
</html>
"""


@app.route("/panel")
@app.route("/admin/turnos")
@requiere_admin
def panel_admin():
    expirar_reservas()
    buscar = request.args.get("buscar", "").strip()
    fecha_filtro = request.args.get("fecha", "").strip()
    sena_filtro = request.args.get("sena", "").strip()

    consulta = "SELECT * FROM turnos WHERE estado_turno = 'reservado'"
    parametros = []

    if buscar:
        consulta += " AND (nombre LIKE ? OR telefono LIKE ?)"
        parametros.extend([f"%{buscar}%", f"%{buscar}%"])

    if fecha_filtro:
        try:
            datetime.strptime(fecha_filtro, "%Y-%m-%d")
            consulta += " AND fecha = ?"
            parametros.append(fecha_filtro)
        except ValueError:
            fecha_filtro = ""

    if sena_filtro in ("pendiente", "pagada"):
        consulta += " AND estado_sena = ?"
        parametros.append(sena_filtro)

    consulta += " ORDER BY fecha, hora"

    conexion = conectar()
    try:
        turnos = conexion.execute(consulta, parametros).fetchall()
    finally:
        conexion.close()

    return render_template_string(
        PLANTILLA_ADMIN,
        turnos=turnos,
        buscar=buscar,
        fecha_filtro=fecha_filtro,
        sena_filtro=sena_filtro,
        fechas=fechas_disponibles(fecha_filtro),
        todos_horarios=HORARIOS
    )


# --------------------------------------------------
# MARCAR SEÑA COMO PAGADA
# --------------------------------------------------

@app.route("/admin/pagada/<int:turno_id>", methods=["POST"])
@requiere_admin
def marcar_pagada(turno_id):
    conexion = conectar()
    try:
        resultado = conexion.execute("""
            UPDATE turnos SET estado_sena = 'pagada'
            WHERE id = ? AND estado_turno = 'reservado'
        """, (turno_id,))
        conexion.commit()

        if resultado.rowcount:
            flash("La seña quedó marcada como pagada.", "success")
        else:
            flash("No se encontró el turno activo.", "error")
    finally:
        conexion.close()

    return redirect(url_for("panel_admin"))


# --------------------------------------------------
# RESERVAR MANUALMENTE DESDE ADMIN
# --------------------------------------------------

@app.route("/admin/reservar", methods=["POST"])
@requiere_admin
def admin_reservar():
    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    fecha_texto = request.form.get("fecha", "").strip()
    hora = request.form.get("hora", "").strip()
    estado_sena = request.form.get("estado_sena", "pendiente")

    if not nombre or not telefono or len(nombre) > 100 or len(telefono) > 40:
        flash("Completá correctamente el nombre y el teléfono.", "error")
        return redirect(url_for("panel_admin"))

    if not fecha_valida(fecha_texto) or hora not in HORARIOS:
        flash("La fecha o el horario no son válidos.", "error")
        return redirect(url_for("panel_admin"))

    if estado_sena not in ("pendiente", "pagada"):
        estado_sena = "pendiente"

    expirar_reservas()
    conexion = conectar()
    try:
        ocupada = conexion.execute("""
            SELECT id FROM turnos
            WHERE fecha = ? AND hora = ? AND estado_turno = 'reservado'
        """, (fecha_texto, hora)).fetchone()

        if ocupada:
            flash("Ese horario ya está ocupado.", "error")
            return redirect(url_for("panel_admin"))

        conexion.execute("""
            INSERT INTO turnos
                (nombre, telefono, fecha, hora, estado_sena,
                 creado_en, origen, estado_turno)
            VALUES (?, ?, ?, ?, ?, ?, 'admin', 'reservado')
        """, (
            nombre, telefono, fecha_texto, hora, estado_sena,
            datetime.now().isoformat(timespec="seconds")
        ))
        conexion.commit()
        flash("Turno guardado correctamente.", "success")
    finally:
        conexion.close()

    return redirect(url_for("panel_admin"))


# --------------------------------------------------
# EDITAR TURNO
# --------------------------------------------------

PAGINA_MODIFICAR = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Modificar turno</title>
""" + ESTILOS + """
</head>
<body>
<div class="contenedor">
    <h1>Modificar turno</h1>

    {% with mensajes = get_flashed_messages(with_categories=true) %}
      {% for categoria, mensaje in mensajes %}
        <div class="{{ 'error' if categoria == 'error' else 'exito' }}">{{ mensaje }}</div>
      {% endfor %}
    {% endwith %}

    <form method="POST">
        <label>Nombre y apellido</label>
        <input name="nombre" value="{{ turno['nombre'] }}" maxlength="100" required>
        <label>Teléfono</label>
        <input name="telefono" value="{{ turno['telefono'] }}" maxlength="40" required>

        <label>Fecha</label>
        <select name="fecha" required>
          {% for fecha in fechas %}
            <option value="{{ fecha }}" {% if fecha == turno['fecha'] %}selected{% endif %}>
              {{ fecha|etiqueta_fecha }}
            </option>
          {% endfor %}
        </select>

        <label>Horario</label>
        <select name="hora" required>
          {% for hora in todos_horarios %}
            <option value="{{ hora }}" {% if hora == turno['hora'] %}selected{% endif %}>{{ hora }}</option>
          {% endfor %}
        </select>

        <label>Estado de la seña</label>
        <select name="estado_sena">
          <option value="pendiente" {% if turno['estado_sena'] == 'pendiente' %}selected{% endif %}>Pendiente</option>
          <option value="pagada" {% if turno['estado_sena'] == 'pagada' %}selected{% endif %}>Pagada</option>
        </select>
        <button type="submit">Guardar cambios</button>
    </form>
    <a class="boton secundario" href="{{ url_for('panel_admin') }}">Volver al panel</a>
</div>
</body>
</html>
"""


@app.route("/modificar/<int:turno_id>", methods=["GET", "POST"])
@app.route("/admin/editar/<int:turno_id>", methods=["GET", "POST"])
@requiere_admin
def modificar_turno(turno_id):
    conexion = conectar()
    try:
        turno = conexion.execute("""
            SELECT * FROM turnos
            WHERE id = ? AND estado_turno = 'reservado'
        """, (turno_id,)).fetchone()

        if not turno:
            flash("El turno no existe o ya fue cancelado.", "error")
            return redirect(url_for("panel_admin"))

        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            telefono = request.form.get("telefono", "").strip()
            fecha_texto = request.form.get("fecha", "").strip()
            hora = request.form.get("hora", "").strip()
            estado_sena = request.form.get("estado_sena", "pendiente")

            if not nombre or not telefono or len(nombre) > 100 or len(telefono) > 40:
                flash("Completá correctamente el nombre y el teléfono.", "error")
                return redirect(url_for("modificar_turno", turno_id=turno_id))

            if not fecha_valida(fecha_texto) or hora not in HORARIOS:
                flash("La fecha o el horario no son válidos.", "error")
                return redirect(url_for("modificar_turno", turno_id=turno_id))

            if estado_sena not in ("pendiente", "pagada"):
                estado_sena = "pendiente"

            ocupada = conexion.execute("""
                SELECT id FROM turnos
                WHERE fecha = ? AND hora = ?
                  AND estado_turno = 'reservado' AND id != ?
            """, (fecha_texto, hora, turno_id)).fetchone()

            if ocupada:
                flash("Ese horario ya está ocupado por otro turno.", "error")
                return redirect(url_for("modificar_turno", turno_id=turno_id))

            conexion.execute("""
                UPDATE turnos
                SET nombre = ?, telefono = ?, fecha = ?, hora = ?, estado_sena = ?
                WHERE id = ?
            """, (nombre, telefono, fecha_texto, hora, estado_sena, turno_id))
            conexion.commit()
            flash("Turno actualizado correctamente.", "success")
            return redirect(url_for("panel_admin"))

        return render_template_string(
            PAGINA_MODIFICAR,
            turno=turno,
            fechas=fechas_disponibles(turno["fecha"]),
            todos_horarios=HORARIOS
        )
    finally:
        conexion.close()


# --------------------------------------------------
# CANCELAR TURNO
# --------------------------------------------------

@app.route("/cancelar/<int:turno_id>", methods=["POST"])
@app.route("/admin/cancelar/<int:turno_id>", methods=["POST"])
@requiere_admin
def cancelar_turno(turno_id):
    conexion = conectar()
    try:
        resultado = conexion.execute("""
            UPDATE turnos SET estado_turno = 'cancelado'
            WHERE id = ? AND estado_turno = 'reservado'
        """, (turno_id,))
        conexion.commit()
    finally:
        conexion.close()

    if resultado.rowcount:
        flash("Turno cancelado. El horario quedó disponible.", "success")
    else:
        flash("No se encontró un turno activo para cancelar.", "error")

    return redirect(url_for("panel_admin"))


# --------------------------------------------------
# CONSULTAR HORARIOS
# --------------------------------------------------

@app.route("/horarios")
def ver_horarios():
    fecha_texto = request.args.get("fecha", "").strip()
    return {
        "fecha": fecha_texto,
        "disponibles": horarios_disponibles(fecha_texto)
    }


# --------------------------------------------------
# INICIAR APLICACION
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)




