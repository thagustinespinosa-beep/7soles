import csv
import json
import math
import os
import uuid
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'distribuidora-dev-secret-key-change-me')
app.config['PRODUCTS_CSV'] = os.path.join(os.path.dirname(__file__), 'productos_7soles.csv')
app.config['PRODUCTS_STORE'] = os.environ.get(
    'PRODUCTS_STORE_PATH',
    os.path.join(os.path.dirname(__file__), '.productos_7soles.json')
)
app.config['DELIVERY_CONFIG'] = os.environ.get(
    'DELIVERY_CONFIG_PATH',
    os.path.join(os.path.dirname(__file__), '.configuracion.json')
)
ADMIN_USERNAME = 'guille1901'
ADMIN_PASSWORD = 'casla127'
CASH_DISCOUNT_PERCENT = 2

# Configuración para subida de imágenes
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

EXTENSIONES_IMAGEN_PERMITIDAS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def guardar_imagen_producto(archivo, url):
    if archivo and archivo.filename:
        nombre_seguro = secure_filename(archivo.filename)
        extension = nombre_seguro.rsplit('.', 1)[-1].lower() if '.' in nombre_seguro else ''
        if extension not in EXTENSIONES_IMAGEN_PERMITIDAS:
            raise ValueError('Formato de imagen no permitido. Use JPG, PNG, GIF o WEBP.')
        nombre_unico = f'{uuid.uuid4().hex}.{extension}'
        archivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico))
        return nombre_unico

    url = (url or '').strip()
    if not url:
        return None
    partes_url = urlparse(url)
    if partes_url.scheme not in {'http', 'https'} or not partes_url.netloc:
        raise ValueError('La URL de imagen debe comenzar con http:// o https://.')
    return url


def eliminar_imagen_subida(imagen):
    if not imagen or imagen.startswith(('http://', 'https://')):
        return
    ruta = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(imagen))
    if os.path.isfile(ruta):
        os.remove(ruta)

def numero_opcional(valor):
    try:
        return float(valor) if valor not in (None, '') else None
    except (TypeError, ValueError):
        return None


def precio_con_descuento(precio, descuento_pct):
    return round(float(precio) * (1 - float(descuento_pct) / 100), 2)


csv_catalogo_mtime_ns = None


def cargar_catalogo_csv():
    productos = []
    with open(app.config['PRODUCTS_CSV'], newline='', encoding='utf-8-sig') as archivo:
        for producto_id, fila in enumerate(csv.DictReader(archivo), start=1):
            precio = numero_opcional(fila.get('precio'))
            precio_efectivo = numero_opcional(fila.get('desc_efectivo'))
            descuento_pct = numero_opcional(fila.get('descuento_efectivo_pct')) or 0

            if precio is None and precio_efectivo is not None:
                if 0 <= descuento_pct < 100:
                    precio = round(precio_efectivo / (1 - descuento_pct / 100), 2)
                else:
                    precio = precio_efectivo
            precio = round(precio or 0, 2)

            if precio > 0 and precio_efectivo is not None:
                descuento_pct = round((1 - precio_efectivo / precio) * 100, 4)
                precio_final = round(precio_efectivo, 2)
            else:
                descuento_pct = max(0, min(float(descuento_pct), 99.99))
                precio_final = precio_con_descuento(precio, descuento_pct)

            cantidad = numero_opcional(fila.get('cantidad')) or 0
            productos.append({
                'id': producto_id,
                'nombre': (fila.get('producto') or '').strip(),
                'precio': precio,
                'descuento_pct': descuento_pct,
                'precio_final': precio_final,
                'stock': max(0, int(cantidad)),
                'imagen': ''
            })
    return productos


def guardar_catalogo(productos=None, csv_mtime_ns=None):
    contenido = {
        'csv_mtime_ns': csv_mtime_ns if csv_mtime_ns is not None else csv_catalogo_mtime_ns,
        'bebidas': productos if productos is not None else bebidas
    }
    temporal = f"{app.config['PRODUCTS_STORE']}.tmp"
    with open(temporal, 'w', encoding='utf-8') as archivo:
        json.dump(contenido, archivo, ensure_ascii=False, indent=2)
    os.replace(temporal, app.config['PRODUCTS_STORE'])


def inicializar_catalogo():
    global csv_catalogo_mtime_ns
    csv_mtime_ns = os.stat(app.config['PRODUCTS_CSV']).st_mtime_ns
    ruta_store = app.config['PRODUCTS_STORE']
    if os.path.isfile(ruta_store):
        try:
            with open(ruta_store, encoding='utf-8') as archivo:
                guardado = json.load(archivo)
            if guardado.get('csv_mtime_ns') == csv_mtime_ns and isinstance(guardado.get('bebidas'), list):
                csv_catalogo_mtime_ns = csv_mtime_ns
                return guardado['bebidas']
        except (OSError, json.JSONDecodeError):
            pass

    productos = cargar_catalogo_csv()
    csv_catalogo_mtime_ns = csv_mtime_ns
    guardar_catalogo(productos, csv_mtime_ns)
    return productos


bebidas = inicializar_catalogo()

pedidos = []
contador_pedidos = 1

def cargar_configuracion():
    try:
        with open(app.config['DELIVERY_CONFIG'], encoding='utf-8') as archivo:
            guardada = json.load(archivo)
        disponible = guardada.get('delivery_disponible')
        if isinstance(disponible, bool):
            return {'delivery_disponible': disponible}
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return {'delivery_disponible': True}


def guardar_configuracion():
    ruta = app.config['DELIVERY_CONFIG']
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    temporal = f'{ruta}.tmp'
    with open(temporal, 'w', encoding='utf-8') as archivo:
        json.dump(configuracion, archivo, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


configuracion = cargar_configuracion()

# --- RUTAS DE LA TIENDA PÚBLICA ---

@app.route('/')
def cliente_index():
    return render_template(
        'index.html',
        configuracion=configuracion,
        delivery_disponible=configuracion['delivery_disponible']
    )


@app.route('/api/configuracion', methods=['GET'])
def get_configuracion():
    return jsonify({'delivery_disponible': configuracion['delivery_disponible']})

@app.route('/api/bebidas', methods=['GET'])
def get_bebidas():
    return jsonify([
        {**bebida, "disponible": bebida["stock"] > 0 and bebida["precio"] > 0}
        for bebida in bebidas
    ])

@app.route('/api/pedidos/crear', methods=['POST'])
def crear_pedido():
    global contador_pedidos
    data = request.json or {}
    if data.get('entrega') == 'delivery' and not configuracion['delivery_disponible']:
        return jsonify({"status": "error", "mensaje": "Delivery no está disponible actualmente"}), 409
    productos_por_id = {producto['id']: producto for producto in bebidas}
    cantidades = {}
    try:
        for item in data.get('items', []):
            producto_id = int(item.get('id'))
            cantidad = int(item.get('cantidad'))
            if cantidad < 1 or producto_id not in productos_por_id:
                raise ValueError
            cantidades[producto_id] = cantidades.get(producto_id, 0) + cantidad
    except (AttributeError, TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "Detalle del pedido inválido"}), 400

    if not cantidades:
        return jsonify({"status": "error", "mensaje": "El pedido no tiene productos"}), 400

    items_pedido = []
    subtotal = 0
    subtotal_con_descuento_producto = 0
    es_efectivo = data.get('metodoPago') == 'Efectivo'
    for producto_id, cantidad in cantidades.items():
        producto = productos_por_id[producto_id]
        if cantidad > producto['stock']:
            return jsonify({"status": "error", "mensaje": f"Stock insuficiente para {producto['nombre']}"}), 409
        precio_normal = round(float(producto['precio']), 2)
        precio_unitario = round(float(producto.get('precio_final', precio_normal)), 2) if es_efectivo else precio_normal
        total_normal = round(precio_normal * cantidad, 2)
        total_item = round(precio_unitario * cantidad, 2)
        subtotal += total_normal
        subtotal_con_descuento_producto += total_item
        items_pedido.append({
            'id': producto_id,
            'nombre': producto['nombre'],
            'cantidad': cantidad,
            'precio_normal': precio_normal,
            'precio_unitario': precio_unitario,
            'descuento_pct': producto.get('descuento_pct', 0) if es_efectivo else 0,
            'total': total_item
        })

    subtotal = round(subtotal, 2)
    subtotal_con_descuento_producto = round(subtotal_con_descuento_producto, 2)
    descuento_producto = round(subtotal - subtotal_con_descuento_producto, 2) if es_efectivo else 0
    descuento_efectivo = round(subtotal_con_descuento_producto * CASH_DISCOUNT_PERCENT / 100, 2) if es_efectivo else 0
    subtotal_productos = round(subtotal_con_descuento_producto - descuento_efectivo, 2)
    es_delivery = data.get('entrega') == 'delivery'
    costo_envio = None if es_delivery else 0
    total = subtotal_productos if costo_envio is None else round(subtotal_productos + costo_envio, 2)
    nuevo_pedido = {
        "id": contador_pedidos,
        "cliente": data.get("nombre"),
        "telefono": data.get("telefono"),
        "entrega": data.get("entrega"),
        "direccion": data.get("direccion"),
        "metodoPago": data.get("metodoPago"),
        "items": items_pedido,
        "subtotal": subtotal,
        "subtotal_productos": subtotal_productos,
        "descuento_producto": descuento_producto,
        "descuento_efectivo": descuento_efectivo,
        "costo_envio": costo_envio,
        "estado_envio": "A confirmar por el vendedor" if es_delivery else "No aplica",
        "total": total,
        "estado": "Pendiente",
        "motivo_rechazo": ""
    }
    
    pedidos.append(nuevo_pedido)
    p_id = contador_pedidos
    contador_pedidos += 1
    
    return jsonify({"status": "ok", "pedido_id": p_id, "total": nuevo_pedido['total']})

@app.route('/api/pedidos/estado/<int:pedido_id>', methods=['GET'])
def consultar_estado_pedido(pedido_id):
    for p in pedidos:
        if p['id'] == pedido_id:
            return jsonify({
                "status": "ok",
                "id": p['id'],
                "estado": p['estado'],
                "motivo_rechazo": p.get('motivo_rechazo', ''),
                "entrega": p.get('entrega'),
                "subtotal_productos": p.get('subtotal_productos', p.get('total', 0)),
                "costo_envio": p.get('costo_envio'),
                "estado_envio": p.get('estado_envio', 'A confirmar por el vendedor' if p.get('entrega') == 'delivery' else 'No aplica'),
                "total": p.get('total', 0)
            })
    return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404


# --- RUTAS DE ADMINISTRACIÓN ---

def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get('admin_authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({"status": "error", "mensaje": "No autorizado"}), 401
            return redirect(url_for('admin_login'))
        return view(*args, **kwargs)
    return wrapped_view

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_authenticated'] = True
            return redirect(url_for('admin'))
        error = 'Nombre de usuario o contraseña incorrectos.'
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout', methods=['POST'])
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html', configuracion=configuracion)

@app.route('/api/admin/bebidas', methods=['GET'])
@admin_required
def admin_get_bebidas():
    return jsonify(bebidas)

@app.route('/api/admin/pedidos', methods=['GET'])
@admin_required
def admin_get_pedidos():
    return jsonify(pedidos)

@app.route('/api/admin/agregar_producto', methods=['POST'])
@admin_required
def agregar_producto():
    nombre = (request.form.get('nombre') or '').strip()
    precio = numero_opcional(request.form.get('precio'))
    descuento_pct = numero_opcional(request.form.get('descuento_pct'))
    stock = numero_opcional(request.form.get('stock'))
    if not nombre or precio is None or precio < 0 or descuento_pct is None or not 0 <= descuento_pct < 100 or stock is None or stock < 0:
        return jsonify({"status": "error", "mensaje": "Revise nombre, precio, descuento y stock"}), 400
    try:
        nombre_imagen = guardar_imagen_producto(
            request.files.get('imagen'),
            request.form.get('imagen_url')
        ) or ''
    except ValueError as error:
        return jsonify({"status": "error", "mensaje": str(error)}), 400

    nuevo_id = max([b['id'] for b in bebidas], default=0) + 1
    nueva_bebida = {
        "id": nuevo_id,
        "nombre": nombre,
        "precio": round(precio, 2),
        "descuento_pct": round(descuento_pct, 4),
        "precio_final": precio_con_descuento(precio, descuento_pct),
        "stock": int(stock),
        "imagen": nombre_imagen
    }
    bebidas.append(nueva_bebida)
    guardar_catalogo()
    return jsonify({"status": "ok", "mensaje": "Producto agregado"})

@app.route('/api/admin/actualizar_producto', methods=['POST'])
@admin_required
def actualizar_producto():
    data = request.json or {}
    try:
        p_id = int(data.get('id'))
        nuevo_precio = float(data.get('precio'))
        descuento_pct = float(data.get('descuento_pct'))
        nuevo_stock = int(data.get('stock'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "Precio, descuento o stock inválido"}), 400
    if nuevo_precio < 0 or not 0 <= descuento_pct < 100 or nuevo_stock < 0:
        return jsonify({"status": "error", "mensaje": "Precio, descuento o stock fuera de rango"}), 400

    for b in bebidas:
        if b['id'] == p_id:
            b['precio'] = round(nuevo_precio, 2)
            b['descuento_pct'] = round(descuento_pct, 4)
            b['precio_final'] = precio_con_descuento(nuevo_precio, descuento_pct)
            b['stock'] = nuevo_stock
            guardar_catalogo()
            return jsonify({"status": "ok", "mensaje": "Producto actualizado"})
    return jsonify({"status": "error", "mensaje": "Producto no encontrado"}), 404


@app.route('/api/admin/actualizar_imagen', methods=['POST'])
@admin_required
def actualizar_imagen_producto():
    try:
        producto_id = int(request.form.get('id'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "ID de producto inválido."}), 400

    producto = next((bebida for bebida in bebidas if bebida['id'] == producto_id), None)
    if producto is None:
        return jsonify({"status": "error", "mensaje": "Producto no encontrado"}), 404

    try:
        nueva_imagen = guardar_imagen_producto(
            request.files.get('imagen'),
            request.form.get('imagen_url')
        )
    except ValueError as error:
        return jsonify({"status": "error", "mensaje": str(error)}), 400

    if nueva_imagen is None:
        return jsonify({"status": "error", "mensaje": "Seleccioná un archivo o ingresá una URL de imagen."}), 400

    imagen_anterior = producto.get('imagen', '')
    producto['imagen'] = nueva_imagen
    try:
        guardar_catalogo()
    except OSError as error:
        producto['imagen'] = imagen_anterior
        if nueva_imagen != imagen_anterior:
            eliminar_imagen_subida(nueva_imagen)
        return jsonify({"status": "error", "mensaje": f"No se pudo guardar la imagen: {error}"}), 500

    if nueva_imagen != imagen_anterior:
        eliminar_imagen_subida(imagen_anterior)
    return jsonify({"status": "ok", "imagen": nueva_imagen, "mensaje": "Imagen actualizada"})

@app.route('/api/admin/eliminar_producto', methods=['POST'])
@admin_required
def eliminar_producto():
    data = request.json or {}
    try:
        producto_id = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "ID de producto inválido"}), 400

    for bebida in bebidas:
        if bebida['id'] == producto_id:
            bebidas.remove(bebida)
            eliminar_imagen_subida(bebida.get('imagen'))
            guardar_catalogo()
            return jsonify({"status": "ok", "mensaje": "Producto eliminado"})
    return jsonify({"status": "error", "mensaje": "Producto no encontrado"}), 404

@app.route('/api/admin/sincronizar_csv', methods=['POST'])
@admin_required
def sincronizar_csv():
    global bebidas, csv_catalogo_mtime_ns
    try:
        bebidas = cargar_catalogo_csv()
        csv_catalogo_mtime_ns = os.stat(app.config['PRODUCTS_CSV']).st_mtime_ns
        guardar_catalogo()
    except (OSError, csv.Error) as error:
        return jsonify({"status": "error", "mensaje": f"No se pudo importar el CSV: {error}"}), 500
    return jsonify({"status": "ok", "cantidad": len(bebidas), "mensaje": "Catálogo sincronizado desde el CSV"})

@app.route('/api/admin/toggle_delivery', methods=['POST', 'PUT'])
@admin_required
def toggle_delivery():
    data = request.get_json(silent=True) or {}
    disponible = data.get('disponible')
    if not isinstance(disponible, bool):
        return jsonify({"status": "error", "mensaje": "El estado debe ser verdadero o falso"}), 400
    estado_anterior = configuracion['delivery_disponible']
    configuracion['delivery_disponible'] = disponible
    try:
        guardar_configuracion()
    except OSError as error:
        configuracion['delivery_disponible'] = estado_anterior
        return jsonify({"status": "error", "mensaje": f"No se pudo guardar la configuración: {error}"}), 500
    return jsonify({
        "status": "ok",
        "delivery_disponible": configuracion['delivery_disponible'],
        "mensaje": "Delivery habilitado" if disponible else "Delivery deshabilitado"
    })


# --- ACCIONES DEL ADMIN EN PEDIDOS ---

@app.route('/api/admin/aceptar_pedido', methods=['POST'])
@admin_required
def aceptar_pedido():
    data = request.get_json(silent=True) or {}
    try:
        pedido_id = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "ID de pedido inválido"}), 400

    pedido = next((item for item in pedidos if item['id'] == pedido_id), None)
    if pedido is None:
        return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404

    if pedido.get('entrega') == 'delivery':
        costo_enviado = data.get('costo_envio')
        if costo_enviado not in (None, ''):
            try:
                costo_envio = round(float(costo_enviado), 2)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "mensaje": "Ingresá un costo de envío válido."}), 400
            if not math.isfinite(costo_envio) or costo_envio < 0:
                return jsonify({"status": "error", "mensaje": "El costo de envío debe ser un monto válido y no negativo."}), 400
            pedido['costo_envio'] = costo_envio
            pedido['estado_envio'] = 'Asignado por la tienda'

        if pedido.get('costo_envio') is None:
            return jsonify({"status": "error", "mensaje": "Asigná el costo de envío antes de aceptar este pedido."}), 400
        pedido['total'] = round(float(pedido.get('subtotal_productos', pedido.get('total', 0))) + pedido['costo_envio'], 2)

    pedido['estado'] = 'Confirmado'
    return jsonify({
        "status": "ok",
        "mensaje": "Pedido confirmado",
        "pedido_id": pedido_id,
        "estado": pedido['estado'],
        "costo_envio": pedido.get('costo_envio'),
        "total": pedido.get('total')
    })


@app.route('/api/admin/asignar_costo_envio', methods=['POST', 'PUT'])
@admin_required
def asignar_costo_envio():
    data = request.get_json(silent=True) or {}
    try:
        pedido_id = int(data.get('id'))
        costo_envio = round(float(data.get('costo_envio')), 2)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "mensaje": "Ingresá un costo de envío válido."}), 400
    if costo_envio < 0:
        return jsonify({"status": "error", "mensaje": "El costo de envío no puede ser negativo."}), 400

    pedido = next((item for item in pedidos if item['id'] == pedido_id), None)
    if pedido is None:
        return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404
    if pedido.get('entrega') != 'delivery':
        return jsonify({"status": "error", "mensaje": "El pedido no requiere envío a domicilio."}), 400

    pedido['costo_envio'] = costo_envio
    pedido['estado_envio'] = 'Asignado por la tienda'
    pedido['total'] = round(float(pedido.get('subtotal_productos', pedido.get('total', 0))) + costo_envio, 2)
    return jsonify({
        "status": "ok",
        "pedido_id": pedido_id,
        "costo_envio": costo_envio,
        "subtotal_productos": pedido['subtotal_productos'],
        "total": pedido['total'],
        "estado_envio": pedido['estado_envio'],
        "mensaje": "Costo de envío guardado y total recalculado"
    })

@app.route('/api/admin/rechazar_pedido', methods=['POST'])
@admin_required
def rechazar_pedido():
    data = request.json
    pedido_id = int(data.get('id'))
    motivo = (data.get('motivo') or '').strip()
    if not motivo:
        return jsonify({"status": "error", "mensaje": "Debe indicar el motivo del rechazo"}), 400
    
    for p in pedidos:
        if p['id'] == pedido_id:
            p['estado'] = 'Rechazado'
            p['motivo_rechazo'] = motivo
            return jsonify({
                "status": "ok", 
                "mensaje": "Pedido rechazado",
                "pedido_id": pedido_id,
                "estado": p['estado'],
                "motivo_rechazo": motivo
            })
            
    return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404

@app.route('/api/admin/finalizar_pedido', methods=['POST'])
@admin_required
def finalizar_pedido():
    data = request.json
    pedido_id = int(data.get('id'))
    
    for p in pedidos:
        if p['id'] == pedido_id:
            p['estado'] = 'Finalizado'
            return jsonify({
                "status": "ok", 
                "mensaje": "Pedido finalizado",
                "pedido_id": pedido_id,
                "estado": p['estado']
            })
            
    return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404


if __name__ == '__main__':
    app.run(debug=True, port=5000)