#version 300 es
out mediump vec4 outColour;

in mediump vec3 position;

uniform samplerCube skybox;

void main()
{
	outColour = texture(skybox, normalize(position));
}
