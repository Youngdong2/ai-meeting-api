from rest_framework.renderers import JSONRenderer


class APIRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get('response') if renderer_context else None

        # Check if data is already wrapped by exception handler
        if isinstance(data, dict) and 'success' in data and 'error' in data and 'data' in data:
            return super().render(data, accepted_media_type, renderer_context)

        if response is not None and response.status_code >= 400:
            response_data = {
                'success': False,
                'error': {
                    'code': response.status_code,
                    'message': data.get('detail', data) if isinstance(data, dict) else data,
                },
                'data': None,
            }
        else:
            response_data = {
                'success': True,
                'error': None,
                'data': data,
            }

        return super().render(response_data, accepted_media_type, renderer_context)
