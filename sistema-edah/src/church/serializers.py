from rest_framework import serializers
from church.models.user import User, TemaPreferencia


class ThemePreferenceSerializer(serializers.ModelSerializer):
    """Serializador para validacao e persistencia de preferencia de tema do usuario."""
    
    theme = serializers.ChoiceField(
        choices=TemaPreferencia.choices,
        source='theme_preference',
        required=True,
        help_text='Tema preferido: light ou dark'
    )

    class Meta:
        model = User
        fields = ['theme']

    def validate_theme(self, value):
        """Validar que o valor de theme esteja nos valores aceitos."""
        if value not in [TemaPreferencia.CLARO, TemaPreferencia.ESCURO]:
            raise serializers.ValidationError(
                f"Tema inválido. Valores aceitos: {TemaPreferencia.CLARO}, {TemaPreferencia.ESCURO}"
            )
        return value

    def update(self, instance, validated_data):
        """Atualizar preferencia de tema do usuario."""
        instance.theme_preference = validated_data.get('theme_preference', instance.theme_preference)
        instance.save()
        return instance
