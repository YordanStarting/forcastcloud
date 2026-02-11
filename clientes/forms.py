from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Cliente, Proveedor, PerfilUsuario, CIUDAD_CHOICES

class ClienteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                base_class = 'form-check-input'
            else:
                base_class = 'form-control'
            current_class = field.widget.attrs.get('class', '')
            if base_class not in current_class:
                field.widget.attrs['class'] = f"{current_class} {base_class}".strip()

    class Meta:
        model = Cliente
        fields = '__all__'

class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = [
            'nombre',
            'nit',
            'contacto',
            'telefono',
            'email',
            'activo',
        ]


class UsuarioBaseForm(forms.ModelForm):
    rol = forms.ChoiceField(choices=PerfilUsuario.ROL_CHOICES, label='Rol')
    ciudad = forms.ChoiceField(choices=CIUDAD_CHOICES, label='Ciudad')

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'is_active',
        ]
        labels = {
            'username': 'Usuario',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo',
            'is_active': 'Activo',
        }


class UsuarioCrearForm(UsuarioBaseForm):
    password1 = forms.CharField(
        label='Contrasena',
        widget=forms.PasswordInput
    )
    password2 = forms.CharField(
        label='Confirmar contrasena',
        widget=forms.PasswordInput
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Las contrasenas no coinciden.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            PerfilUsuario.objects.update_or_create(
                usuario=user,
                defaults={
                    'rol': self.cleaned_data['rol'],
                    'ciudad': self.cleaned_data['ciudad'],
                }
            )
        return user


class UsuarioEditarForm(UsuarioBaseForm):
    password1 = forms.CharField(
        label='Nueva contrasena',
        widget=forms.PasswordInput,
        required=False
    )
    password2 = forms.CharField(
        label='Confirmar nueva contrasena',
        widget=forms.PasswordInput,
        required=False
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 or password2:
            if password1 != password2:
                self.add_error('password2', 'Las contrasenas no coinciden.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password1 = self.cleaned_data.get('password1')
        if password1:
            user.set_password(password1)
        if commit:
            user.save()
            PerfilUsuario.objects.update_or_create(
                usuario=user,
                defaults={
                    'rol': self.cleaned_data['rol'],
                    'ciudad': self.cleaned_data['ciudad'],
                }
            )
        return user


class MiPerfilForm(forms.ModelForm):
    foto_perfil = forms.ImageField(required=False, label='Foto de perfil')
    eliminar_foto = forms.BooleanField(required=False, label='Quitar foto actual')
    current_password = forms.CharField(
        label='Contrasena actual',
        widget=forms.PasswordInput,
        required=False
    )
    new_password1 = forms.CharField(
        label='Nueva contrasena',
        widget=forms.PasswordInput,
        required=False
    )
    new_password2 = forms.CharField(
        label='Confirmar nueva contrasena',
        widget=forms.PasswordInput,
        required=False
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        current_password = cleaned_data.get('current_password')
        new_password1 = cleaned_data.get('new_password1')
        new_password2 = cleaned_data.get('new_password2')

        wants_password_change = bool(current_password or new_password1 or new_password2)
        if not wants_password_change:
            return cleaned_data

        if not current_password:
            self.add_error('current_password', 'Debes ingresar tu contrasena actual.')
            return cleaned_data

        if not self.user or not self.user.check_password(current_password):
            self.add_error('current_password', 'La contrasena actual no es valida.')
            return cleaned_data

        if not new_password1:
            self.add_error('new_password1', 'Debes ingresar una nueva contrasena.')
            return cleaned_data

        if not new_password2:
            self.add_error('new_password2', 'Debes confirmar la nueva contrasena.')
            return cleaned_data

        if new_password1 != new_password2:
            self.add_error('new_password2', 'Las contrasenas no coinciden.')
            return cleaned_data

        try:
            validate_password(new_password1, self.user)
        except ValidationError as error:
            self.add_error('new_password1', error)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password1 = self.cleaned_data.get('new_password1')
        if new_password1:
            user.set_password(new_password1)
        if commit:
            user.save()
        return user

