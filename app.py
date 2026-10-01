import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'distribuidora-dev-secret-key-change-me')
ADMIN_USERNAME = 'guille1901'
ADMIN_PASSWORD = 'casla127'

# Configuración para subida de imágenes
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Base de datos en memoria
bebidas = [
    {"id": 1, "nombre": "Cerveza Quilmes 1L", "precio": 2500, "stock": 50, "imagen": ""},
    {"id": 2, "nombre": "Fernet Branca 750ml", "precio": 8500, "stock": 20, "imagen": ""},
    {"id": 3, "nombre": "Coca-Cola 2.25L", "precio": 3100, "stock": 35, "imagen": ""}
]

pedidos = []
contador_pedidos = 1

configuracion = {
    "delivery_disponible": True
}

# --- RUTAS DE LA TIENDA PÚBLICA ---

@app.route('/')
def cliente_index():
    return render_template('index.html', configuracion=configuracion)

@app.route('/api/bebidas', methods=['GET'])
def get_bebidas():
    return jsonify([
        {**bebida, "disponible": bebida["stock"] > 0}
        for bebida in bebidas
    ])

@app.route('/api/pedidos/crear', methods=['POST'])
def crear_pedido():
    global contador_pedidos
    data = request.json
    
    nuevo_pedido = {
        "id": contador_pedidos,
        "cliente": data.get("nombre"),
        "telefono": data.get("telefono"),
        "entrega": data.get("entrega"),
        "direccion": data.get("direccion"),
        "metodoPago": data.get("metodoPago"),
        "items": data.get("items", []),
        "total": data.get("total"),
        "estado": "Pendiente",
        "motivo_rechazo": ""
    }
    
    pedidos.append(nuevo_pedido)
    p_id = contador_pedidos
    contador_pedidos += 1
    
    return jsonify({"status": "ok", "pedido_id": p_id})

@app.route('/api/pedidos/estado/<int:pedido_id>', methods=['GET'])
def consultar_estado_pedido(pedido_id):
    for p in pedidos:
        if p['id'] == pedido_id:
            return jsonify({
                "status": "ok",
                "id": p['id'],
                "estado": p['estado'],
                "motivo_rechazo": p.get('motivo_rechazo', '')
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
    nombre = request.form.get('nombre')
    precio = float(request.form.get('precio', 0))
    stock = int(request.form.get('stock', 0))
    imagen = request.files.get('imagen')

    nombre_imagen = ""
    if imagen and imagen.filename != '':
        nombre_imagen = secure_filename(imagen.filename)
        imagen.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_imagen))

    nuevo_id = max([b['id'] for b in bebidas], default=0) + 1
    nueva_bebida = {
        "id": nuevo_id,
        "nombre": nombre,
        "precio": precio,
        "stock": stock,
        "imagen": nombre_imagen
    }
    bebidas.append(nueva_bebida)
    return jsonify({"status": "ok", "mensaje": "Producto agregado"})

@app.route('/api/admin/actualizar_producto', methods=['POST'])
@admin_required
def actualizar_producto():
    data = request.json
    p_id = int(data.get('id'))
    nuevo_precio = float(data.get('precio'))
    nuevo_stock = int(data.get('stock'))

    for b in bebidas:
        if b['id'] == p_id:
            b['precio'] = nuevo_precio
            b['stock'] = nuevo_stock
            return jsonify({"status": "ok", "mensaje": "Producto actualizado"})
    return jsonify({"status": "error", "mensaje": "Producto no encontrado"}), 404

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
            if bebida.get('imagen'):
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(bebida['imagen']))
                if os.path.isfile(image_path):
                    os.remove(image_path)
            return jsonify({"status": "ok", "mensaje": "Producto eliminado"})
    return jsonify({"status": "error", "mensaje": "Producto no encontrado"}), 404

@app.route('/api/admin/toggle_delivery', methods=['POST'])
@admin_required
def toggle_delivery():
    data = request.json
    configuracion["delivery_disponible"] = bool(data.get('disponible'))
    return jsonify({"status": "ok", "delivery_disponible": configuracion["delivery_disponible"]})


# --- ACCIONES DEL ADMIN EN PEDIDOS ---

@app.route('/api/admin/aceptar_pedido', methods=['POST'])
@admin_required
def aceptar_pedido():
    data = request.json
    pedido_id = int(data.get('id'))
    
    for p in pedidos:
        if p['id'] == pedido_id:
            p['estado'] = 'Confirmado'
            num_tel = ''.join(filter(str.isdigit, str(p.get('telefono', ''))))
            mensaje_texto = f"¡Hola {p['cliente']}! 👋 Tu pedido N°{p['id']} ha sido CONFIRMADO y ya está en proceso. Total: ${p['total']}."
            
            return jsonify({
                "status": "ok", 
                "mensaje": "Pedido confirmado",
                "telefono": num_tel,
                "texto_whatsapp": mensaje_texto
            })
            
    return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404

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
            num_tel = ''.join(filter(str.isdigit, str(p.get('telefono', ''))))
            mensaje_texto = f"Hola {p['cliente']}. Lamentablemente tu pedido N°{p['id']} no pudo ser procesado. Motivo: {motivo}"
            
            return jsonify({
                "status": "ok", 
                "mensaje": "Pedido rechazado",
                "telefono": num_tel,
                "texto_whatsapp": mensaje_texto
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
            num_tel = ''.join(filter(str.isdigit, str(p.get('telefono', ''))))
            mensaje_texto = f"¡Hola {p['cliente']}! 🚀 Tu pedido N°{p['id']} ha sido COMPLETADO. ¡Gracias por tu compra!"
            
            return jsonify({
                "status": "ok", 
                "mensaje": "Pedido finalizado",
                "telefono": num_tel,
                "texto_whatsapp": mensaje_texto
            })
            
    return jsonify({"status": "error", "mensaje": "Pedido no encontrado"}), 404


if __name__ == '__main__':
    app.run(debug=True, port=5000)