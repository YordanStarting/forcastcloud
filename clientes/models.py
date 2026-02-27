from django.db import models
from django.contrib.auth.models import User
from datetime import date

TIPO_HUEVO_CHOICES = [
    ('HELU', 'Huevo Líquido Entero'),
    ('YELU', 'Yema Líquida'),
    ('CLLU', 'Clara Líquida'),
    ('MEPU', 'Mezcla en Polvo'),
    ('HEPU', 'Huevo en Polvo'),
    ('YEPU', 'Yema en Polvo'),
    ('ALBP', 'Albumina en Polvo'),
]

PRESENTACION_CHOICES = [
    ('OV20_1000', 'OV20 1000'),
    ('OV20_20', 'OV20 x 20'),
    ('OV20_15', 'OV20 x 15'),
    ('OV15_200', 'OV15 200'),
    ('OV15_20', 'OV15 20'),
    ('OV15_15', 'OV15 15'),
    ('OV15_14', 'OV15 14'),
    ('OV30_20', 'OV30-20'),
    ('OV30_10', 'OV30-10'),
    ('OV30_5', 'OV30-5'),
    ('OV30_3', 'OV30-3'),
    ('OV30_3KG', 'OV30 x 3Kg'),
    ('SAC_20', 'Sac x 20'),
    ('BOLSA_4_4KG', 'Bolsa 4,4Kg'),
    ('POLVO_DOSIF_2KG', 'Polvo dosificado 2 kilos'),
]

CIUDAD_CHOICES = [
    ('BOGOTA', 'Bogota'),
    ('MEDELLIN', 'Medellin'),
    ('CALI', 'Cali'),
]

class Cliente(models.Model):
    id = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    imagen = models.ImageField(upload_to='imagenes/', verbose_name="Imagen", null=True)
    descripcion = models.TextField(max_length=500)

    def __str__(self):
        return f"{self.titulo} - {self.descripcion[:50]}..."
    
    def delete(self, *args, **kwargs):
        if self.imagen:
            self.imagen.delete(save=False)
        super().delete(*args, **kwargs)

class Proveedor(models.Model):
    nombre = models.CharField(max_length=150, default='Proveedor sin nombre')
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA')
    presentacion = models.CharField(
        max_length=20,
        choices=PRESENTACION_CHOICES,
        default='OV20_1000'
    )
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

class PerfilUsuario(models.Model):
    ROL_CHOICES = [
        ('admin', 'Administrador'),
        ('comercial', 'Comercial'),
        ('logistica', 'Logistica'),
        ('produccion', 'Produccion'),
        ('programador', 'Programador'),
    ]
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=20, choices=ROL_CHOICES)
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA')
    foto_perfil = models.ImageField(upload_to='perfiles/', null=True, blank=True)

    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"

class Notificacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True)
    mensaje = models.TextField()
    tipo_evento = models.CharField(
        max_length=30,
        choices=[
            ('INFO', 'Informacion'),
            ('PEDIDO_CREADO', 'Pedido creado'),
            ('PEDIDO_CONFIRMADO', 'Pedido confirmado'),
            ('PEDIDO_CANCELADO', 'Pedido cancelado'),
            ('PEDIDO_DEVUELTO', 'Pedido devuelto'),
            ('PEDIDO_CAMBIO_ESTADO', 'Cambio de estado'),
        ],
        default='INFO',
    )
    reproducir_sonido = models.BooleanField(default=False, db_index=True)
    leida = models.BooleanField(default=False, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['usuario', 'leida', 'fecha_creacion']),
            models.Index(fields=['usuario', 'reproducir_sonido', 'fecha_creacion']),
        ]
    
    def __str__(self):
        if self.usuario:
            return f"Notificación para {self.usuario.username}"
        return f"Notificación: {self.mensaje[:50]}..."

class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('CONFIRMADO', 'Confirmado'),
        ('EN_PRODUCCION', 'En produccion'),
        ('DESPACHADO', 'Despachado'),
        ('ENTREGADO', 'Entregado'),
        ('CANCELADO', 'Cancelado'),
        ('DEVUELTO', 'Devuelto'),
    ]
    
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    comercial = models.ForeignKey(User, on_delete=models.PROTECT)
    ciudad = models.CharField(max_length=20, choices=CIUDAD_CHOICES, default='BOGOTA', db_index=True)
    
    tipo_huevo = models.CharField(max_length=10, choices=TIPO_HUEVO_CHOICES, db_index=True)
    presentacion = models.CharField(max_length=20, choices=PRESENTACION_CHOICES, db_index=True)
    
    # CAMPOS QUE USAS EN LAS VISTAS:
    cantidad = models.IntegerField(default=0)
    fecha_entrega = models.DateField(null=True, blank=True, db_index=True)
    
    # Campos adicionales (si los necesitas):
    cantidad_total = models.IntegerField(default=0)
    fabricado_kg = models.IntegerField(default=0)
    despachado_kg = models.IntegerField(default=0)
    semana = models.DateField(
        help_text="Lunes de la semana", 
        null=True, 
        blank=True,
        db_index=True,
    )
    
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='PENDIENTE',
        db_index=True,
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)
    observaciones = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['estado', 'fecha_creacion']),
            models.Index(fields=['semana', 'estado']),
            models.Index(fields=['ciudad', 'estado']),
            models.Index(fields=['semana', 'presentacion', 'tipo_huevo']),
        ]
    
    def __str__(self):
        return f"Pedido #{self.id} - {self.proveedor.nombre}"


class MateriaPrima(models.Model):
    fecha = models.DateField(default=date.today, db_index=True)
    tipo_huevo = models.CharField(max_length=10, choices=TIPO_HUEVO_CHOICES, db_index=True)
    cantidad_kg = models.IntegerField()
    observaciones = models.TextField(blank=True, null=True)
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='materias_primas_creadas',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-id']
        indexes = [
            models.Index(fields=['fecha', 'tipo_huevo']),
        ]

    def __str__(self):
        return f"{self.get_tipo_huevo_display()} - {self.cantidad_kg} kg ({self.fecha})"


class EntregaPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        related_name='entregas',
        on_delete=models.CASCADE
    )
    
    fecha_entrega = models.DateField(db_index=True)
    cantidad = models.IntegerField()
    
    estado = models.CharField(
        max_length=10,
        choices=[
            ('PENDIENTE', 'Pendiente'),
            ('ENTREGADO', 'Entregado'),
        ],
        default='PENDIENTE',
        db_index=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=['pedido', 'fecha_entrega']),
            models.Index(fields=['estado', 'fecha_entrega']),
        ]
    
    def __str__(self):
        return f"Entrega para Pedido #{self.pedido.id} - {self.fecha_entrega}"


class RegistroEstadoPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        related_name='registros_estado',
        on_delete=models.CASCADE
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    estado_anterior = models.CharField(
        max_length=20,
        choices=Pedido.ESTADO_CHOICES
    )
    estado_nuevo = models.CharField(
        max_length=20,
        choices=Pedido.ESTADO_CHOICES,
        db_index=True,
    )
    descripcion = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['estado_nuevo', 'fecha_creacion']),
            models.Index(fields=['pedido', 'fecha_creacion']),
        ]

    def __str__(self):
        return (
            f"Pedido #{self.pedido_id}: {self.estado_anterior} -> "
            f"{self.estado_nuevo}"
        )


class RegistroProduccion(models.Model):
    ACCION_CHOICES = [
        ('FABRICADO_ACTUALIZADO', 'Fabricado actualizado'),
        ('ESTADO_EN_PRODUCCION', 'Cambio a en produccion'),
        ('MATERIA_PRIMA_REGISTRADA', 'Materia prima registrada'),
    ]

    pedido = models.ForeignKey(
        Pedido,
        related_name='registros_produccion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_produccion',
    )
    accion = models.CharField(max_length=40, choices=ACCION_CHOICES, db_index=True)
    sucursal = models.CharField(max_length=20, blank=True, default='')
    compania = models.CharField(max_length=150, blank=True, default='')
    tipo_huevo = models.CharField(max_length=80, blank=True, default='')
    presentacion = models.CharField(max_length=80, blank=True, default='')
    valor_anterior = models.IntegerField(null=True, blank=True)
    valor_nuevo = models.IntegerField(null=True, blank=True)
    cantidad_kg = models.IntegerField(null=True, blank=True)
    detalle = models.TextField(blank=True, default='')
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-fecha_creacion', '-id']
        indexes = [
            models.Index(fields=['accion', 'fecha_creacion']),
            models.Index(fields=['sucursal', 'fecha_creacion']),
            models.Index(fields=['pedido', 'fecha_creacion']),
        ]

    def __str__(self):
        return f"{self.get_accion_display()} - {self.fecha_creacion:%Y-%m-%d %H:%M}"


class DespachoPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        related_name='despachos',
        on_delete=models.CASCADE,
    )
    fecha = models.DateField(db_index=True)
    cantidad = models.IntegerField(default=0)
    creado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='despachos_creados',
    )
    actualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='despachos_actualizados',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', '-id']
        constraints = [
            models.UniqueConstraint(fields=['pedido', 'fecha'], name='unique_despacho_por_pedido_fecha'),
        ]
        indexes = [
            models.Index(fields=['pedido', 'fecha']),
            models.Index(fields=['fecha']),
        ]

    def __str__(self):
        return f"Despacho Pedido #{self.pedido_id} - {self.fecha}: {self.cantidad} kg"


