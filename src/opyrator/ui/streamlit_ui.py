import datetime
import inspect
import mimetypes
import sys
from os import getcwd
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, List, Type

import pandas as pd
import streamlit as st
from fastapi.encoders import jsonable_encoder
from loguru import logger
from pydantic import BaseModel, ValidationError, parse_obj_as

from opyrator import Opyrator
from opyrator.core import name_to_title
from opyrator.ui import schema_utils, streamlit_utils
from opyrator.ui.streamlit_utils import CUSTOM_STREAMLIT_CSS, SessionState

STREAMLIT_RUNNER_SNIPPET = """
from opyrator.ui import render_streamlit_ui
from opyrator import Opyrator

import streamlit as st

st.set_page_config(page_title="Opyrator", page_icon=":arrow_forward:")

with st.spinner("Loading Opyrator. Please wait..."):
    opyrator = Opyrator("{opyrator_path}")

render_streamlit_ui(opyrator)
"""


def launch_ui(opyrator_path: str, port: int = 8501) -> None:
    # import streamlit.bootstrap as bootstrap
    # from streamlit.cli import _get_command_line_as_string
    # print(_get_command_line_as_string())
    with NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8") as f:
        f.write(STREAMLIT_RUNNER_SNIPPET.format(opyrator_path=opyrator_path))
        f.seek(0)

        # TODO: PYTHONPATH="$PYTHONPATH:/workspace/opyrator/src"
        import subprocess

        subprocess.run(
            f'PYTHONPATH="$PYTHONPATH:{getcwd()}" {sys.executable} -m streamlit run --server.port={port} --server.headless=True --runner.magicEnabled=False --server.maxUploadSize=50 --browser.gatherUsageStats=False {f.name}',
            shell=True,
        )


def function_has_named_arg(func: Callable, parameter: str) -> bool:
    try:
        sig = inspect.signature(func)
        for param in sig.parameters.values():
            if param.name == "input":
                return True
    except Exception:
        return False
    return False


def has_output_ui_renderer(data_item: BaseModel) -> bool:
    return hasattr(data_item, "render_output_ui")


def has_input_ui_renderer(input_class: Type[BaseModel]) -> bool:
    return hasattr(input_class, "render_input_ui")


def is_compatible_audio(mime_type: str) -> bool:
    return mime_type in ["audio/mpeg", "audio/ogg", "audio/wav"]


def is_compatible_image(mime_type: str) -> bool:
    return mime_type in ["image/png", "image/jpeg"]


def is_compatible_video(mime_type: str) -> bool:
    return mime_type in ["video/mp4"]


class InputUI:
    def __init__(self, session_state: SessionState, input_class: Type[BaseModel]):
        self._session_state = session_state
        self._input_class = input_class

        self._schema_properties = input_class.schema(by_alias=True).get(
            "properties", {}
        )
        self._schema_references = input_class.schema(by_alias=True).get(
            "definitions", {}
        )

        # TODO: check if state has input data

    def render_ui(self) -> None:
        if has_input_ui_renderer(self._input_class):
            # The input model has a rendering function
            # The rendering also returns the current state of input data
            self._session_state.input_data = self._input_class.render_input_ui(  # type: ignore
                st, self._session_state.input_data
            ).dict()
            return

        required_properties = self._input_class.schema(by_alias=True).get(
            "required", []
        )

        for property_key in self._schema_properties.keys():
            streamlit_app = st.sidebar
            property = self._schema_properties[property_key]

            if not property.get("title"):
                # Set property key as fallback title
                property["title"] = name_to_title(property_key)

            if property_key in required_properties:
                streamlit_app = st

            try:
                self._store_value(
                    property_key,
                    self._render_property(streamlit_app, property_key, property),
                )
            except Exception:
                pass

    def _get_default_streamlit_input_kwargs(self, key: str, property: Dict) -> Dict:
        streamlit_kwargs = {
            "label": property.get("title"),
            "key": str(self._session_state.run_id) + "-" + key,
        }

        if property.get("description"):
            streamlit_kwargs["help"] = property.get("description")
        return streamlit_kwargs

    def _store_value(self, key: str, value: Any) -> None:
        data_element = self._session_state.input_data
        key_elements = key.split(".")
        for i, key_element in enumerate(key_elements):
            if i == len(key_elements) - 1:
                # add value to this element
                data_element[key_element] = value
                return
            if key_element not in data_element:
                data_element[key_element] = {}
            data_element = data_element[key_element]

    def _get_value(self, key: str) -> Any:
        data_element = self._session_state.input_data
        key_elements = key.split(".")
        for i, key_element in enumerate(key_elements):
            if i == len(key_elements) - 1:
                # add value to this element
                if key_element not in data_element:
                    return None
                return data_element[key_element]
            if key_element not in data_element:
                data_element[key_element] = {}
            data_element = data_element[key_element]
        return None

    def _render_single_datetime_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)

        if property.get("format") == "time":
            if property.get("default"):
                try:
                    streamlit_kwargs["value"] = datetime.time.fromisoformat(  # type: ignore
                        property.get("default")
                    )
                except Exception:
                    pass
            return streamlit_app.time_input(**streamlit_kwargs)
        elif property.get("format") == "date":
            if property.get("default"):
                try:
                    streamlit_kwargs["value"] = datetime.date.fromisoformat(  # type: ignore
                        property.get("default")
                    )
                except Exception:
                    pass
            return streamlit_app.date_input(**streamlit_kwargs)
        elif property.get("format") == "date-time":
            if property.get("default"):
                try:
                    streamlit_kwargs["value"] = datetime.datetime.fromisoformat(  # type: ignore
                        property.get("default")
                    )
                except Exception:
                    pass
            with st.beta_container():
                st.subheader(streamlit_kwargs.get("label"))
                if streamlit_kwargs.get("description"):
                    st.text(streamlit_kwargs.get("description"))
                selected_date = None
                selected_time = None
                date_col, time_col = st.beta_columns(2)
                with date_col:
                    date_kwargs = {"label": "Date", "key": key + "-date-input"}
                    if streamlit_kwargs.get("value"):
                        try:
                            date_kwargs["value"] = streamlit_kwargs.get(  # type: ignore
                                "value"
                            ).date()
                        except Exception:
                            pass
                    selected_date = st.date_input(**date_kwargs)

                with time_col:
                    time_kwargs = {"label": "Time", "key": key + "-time-input"}
                    if streamlit_kwargs.get("value"):
                        try:
                            time_kwargs["value"] = streamlit_kwargs.get(  # type: ignore
                                "value"
                            ).time()
                        except Exception:
                            pass
                    selected_time = st.time_input(**time_kwargs)
                return datetime.datetime.combine(selected_date, selected_time)
        else:
            streamlit_app.warning(
                "Date format is not supported: " + str(property.get("format"))
            )

    def _render_single_file_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)
        file_extension = None
        if "mime_type" in property:
            file_extension = mimetypes.guess_extension(property["mime_type"])

        uploaded_file = streamlit_app.file_uploader(
            **streamlit_kwargs, accept_multiple_files=False, type=file_extension
        )
        if uploaded_file is None:
            return None

        bytes = uploaded_file.getvalue()
        if property.get("mime_type"):
            if is_compatible_audio(property["mime_type"]):
                # Show audio
                streamlit_app.audio(bytes, format=property.get("mime_type"))
            if is_compatible_image(property["mime_type"]):
                # Show image
                streamlit_app.image(bytes)
            if is_compatible_video(property["mime_type"]):
                # Show video
                streamlit_app.video(bytes, format=property.get("mime_type"))
        return bytes

    def _render_single_string_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)

        if property.get("default"):
            streamlit_kwargs["value"] = property.get("default")
        elif property.get("example"):
            # TODO: also use example for other property types
            # Use example as value if it is provided
            streamlit_kwargs["value"] = property.get("example")

        if property.get("maxLength") is not None:
            streamlit_kwargs["max_chars"] = property.get("maxLength")

        if (
            property.get("format")
            or (
                property.get("maxLength") is not None
                and int(property.get("maxLength")) < 140  # type: ignore
            )
            or property.get("writeOnly")
        ):
            # If any format is set, use single text input
            # If max chars is set to less than 140, use single text input
            # If write only -> password field
            if property.get("writeOnly"):
                streamlit_kwargs["type"] = "password"
            return streamlit_app.text_input(**streamlit_kwargs)
        else:
            # Otherwise use multiline text area
            return streamlit_app.text_area(**streamlit_kwargs)

    def _render_multi_enum_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)
        reference_item = schema_utils.resolve_reference(
            property["items"]["$ref"], self._schema_references
        )
        # TODO: how to select defaults
        return streamlit_app.multiselect(
            **streamlit_kwargs, options=reference_item["enum"]
        )

    def _render_single_enum_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:

        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)
        reference_item = schema_utils.get_single_reference_item(
            property, self._schema_references
        )

        if property.get("default") is not None:
            try:
                streamlit_kwargs["index"] = reference_item["enum"].index(
                    property.get("default")
                )
            except Exception:
                # Use default selection
                pass

        return streamlit_app.selectbox(
            **streamlit_kwargs, options=reference_item["enum"]
        )

    def _render_single_dict_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:

        # Add title and subheader
        streamlit_app.subheader(property.get("title"))
        if property.get("description"):
            streamlit_app.markdown(property.get("description"))

        streamlit_app.markdown("---")

        current_dict = self._get_value(key)
        if not current_dict:
            current_dict = {}

        key_col, value_col = streamlit_app.beta_columns(2)

        with key_col:
            updated_key = streamlit_app.text_input(
                "Key", value="", key=key + "-new-key"
            )

        with value_col:
            # TODO: also add boolean?
            value_kwargs = {"label": "Value", "key": key + "-new-value"}
            if property["additionalProperties"].get("type") == "integer":
                value_kwargs["value"] = 0  # type: ignore
                updated_value = streamlit_app.number_input(**value_kwargs)
            elif property["additionalProperties"].get("type") == "number":
                value_kwargs["value"] = 0.0  # type: ignore
                value_kwargs["format"] = "%f"
                updated_value = streamlit_app.number_input(**value_kwargs)
            else:
                value_kwargs["value"] = ""
                updated_value = streamlit_app.text_input(**value_kwargs)

        streamlit_app.markdown("---")

        with streamlit_app.beta_container():
            clear_col, add_col = streamlit_app.beta_columns([1, 2])

            with clear_col:
                if streamlit_app.button("Clear Items", key=key + "-clear-items"):
                    current_dict = {}

            with add_col:
                if (
                    streamlit_app.button("Add Item", key=key + "-add-item")
                    and updated_key
                ):
                    current_dict[updated_key] = updated_value

        streamlit_app.write(current_dict)

        return current_dict

    def _render_single_reference(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        reference_item = schema_utils.get_single_reference_item(
            property, self._schema_references
        )
        return self._render_property(streamlit_app, key, reference_item)

    def _render_multi_file_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)

        file_extension = None
        if "mime_type" in property:
            file_extension = mimetypes.guess_extension(property["mime_type"])

        uploaded_files = streamlit_app.file_uploader(
            **streamlit_kwargs, accept_multiple_files=True, type=file_extension
        )
        uploaded_files_bytes = []
        if uploaded_files:
            for uploaded_file in uploaded_files:
                uploaded_files_bytes.append(uploaded_file.read())
        return uploaded_files_bytes

    def _render_single_boolean_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)

        if property.get("default"):
            streamlit_kwargs["value"] = property.get("default")
        return streamlit_app.checkbox(**streamlit_kwargs)

    def _render_single_number_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        streamlit_kwargs = self._get_default_streamlit_input_kwargs(key, property)

        number_transform = int
        if property.get("type") == "number":
            number_transform = float  # type: ignore
            streamlit_kwargs["format"] = "%f"

        if "multipleOf" in property:
            # Set stepcount based on multiple of parameter
            streamlit_kwargs["step"] = number_transform(property["multipleOf"])
        elif number_transform == int:
            # Set step size to 1 as default
            streamlit_kwargs["step"] = 1
        elif number_transform == float:
            # Set step size to 0.01 as default
            # TODO: adapt to default value
            streamlit_kwargs["step"] = 0.01

        if "minimum" in property:
            streamlit_kwargs["min_value"] = number_transform(property["minimum"])
        if "exclusiveMinimum" in property:
            streamlit_kwargs["min_value"] = number_transform(
                property["exclusiveMinimum"] + streamlit_kwargs["step"]
            )
        if "maximum" in property:
            streamlit_kwargs["max_value"] = number_transform(property["maximum"])

        if "exclusiveMaximum" in property:
            streamlit_kwargs["max_value"] = number_transform(
                property["exclusiveMaximum"] - streamlit_kwargs["step"]
            )

        if property.get("default") is not None:
            streamlit_kwargs["value"] = number_transform(property.get("default"))  # type: ignore
        else:
            if "min_value" in streamlit_kwargs:
                streamlit_kwargs["value"] = streamlit_kwargs["min_value"]
            elif number_transform == int:
                streamlit_kwargs["value"] = 0
            else:
                # Set default value to step
                streamlit_kwargs["value"] = number_transform(streamlit_kwargs["step"])

        if "min_value" in streamlit_kwargs and "max_value" in streamlit_kwargs:
            # TODO: Only if less than X steps
            return streamlit_app.slider(**streamlit_kwargs)
        else:
            return streamlit_app.number_input(**streamlit_kwargs)

    def _render_object_input(self, streamlit_app: st, key: str, property: Dict) -> Any:
        properties = property["properties"]
        object_inputs = {}
        for property_key in properties:
            property = properties[property_key]
            if not property.get("title"):
                # Set property key as fallback title
                property["title"] = name_to_title(property_key)
            # construct full key based on key parts -> required later to get the value
            full_key = key + "." + property_key
            object_inputs[property_key] = self._render_property(
                streamlit_app, full_key, property
            )
        return object_inputs

    def _render_single_object_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:
        # Add title and subheader
        title = property.get("title")
        streamlit_app.subheader(title)
        if property.get("description"):
            streamlit_app.markdown(property.get("description"))

        object_reference = schema_utils.get_single_reference_item(
            property, self._schema_references
        )
        return self._render_object_input(streamlit_app, key, object_reference)

    def _render_property_list_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:

        # Add title and subheader
        streamlit_app.subheader(property.get("title"))
        if property.get("description"):
            streamlit_app.markdown(property.get("description"))

        streamlit_app.markdown("---")

        current_list = self._get_value(key)
        if not current_list:
            current_list = []

        value_kwargs = {"label": "Value", "key": key + "-new-value"}
        if property["items"]["type"] == "integer":
            value_kwargs["value"] = 0  # type: ignore
            new_value = streamlit_app.number_input(**value_kwargs)
        elif property["items"]["type"] == "number":
            value_kwargs["value"] = 0.0  # type: ignore
            value_kwargs["format"] = "%f"
            new_value = streamlit_app.number_input(**value_kwargs)
        else:
            value_kwargs["value"] = ""
            new_value = streamlit_app.text_input(**value_kwargs)

        streamlit_app.markdown("---")

        with streamlit_app.beta_container():
            clear_col, add_col = streamlit_app.beta_columns([1, 2])

            with clear_col:
                if streamlit_app.button("Clear Items", key=key + "-clear-items"):
                    current_list = []

            with add_col:
                if (
                    streamlit_app.button("Add Item", key=key + "-add-item")
                    and new_value is not None
                ):
                    current_list.append(new_value)

        streamlit_app.write(current_list)

        return current_list

    def _render_object_list_input(
        self, streamlit_app: st, key: str, property: Dict
    ) -> Any:

        # TODO: support max_items, and min_items properties

        # Add title and subheader
        streamlit_app.subheader(property.get("title"))
        if property.get("description"):
            streamlit_app.markdown(property.get("description"))

        streamlit_app.markdown("---")

        current_list = self._get_value(key)
        if not current_list:
            current_list = []

        object_reference = schema_utils.resolve_reference(
            property["items"]["$ref"], self._schema_references
        )
        input_data = self._render_object_input(streamlit_app, key, object_reference)

        streamlit_app.markdown("---")

        with streamlit_app.beta_container():
            clear_col, add_col = streamlit_app.beta_columns([1, 2])

            with clear_col:
                if streamlit_app.button("Clear Items", key=key + "-clear-items"):
                    current_list = []

            with add_col:
                if (
                    streamlit_app.button("Add Item", key=key + "-add-item")
                    and input_data
                ):
                    current_list.append(input_data)

        streamlit_app.write(current_list)
        return current_list

    def _render_property(self, streamlit_app: st, key: str, property: Dict) -> Any:
        if schema_utils.is_single_enum_property(property, self._schema_references):
            return self._render_single_enum_input(streamlit_app, key, property)

        if schema_utils.is_multi_enum_property(property, self._schema_references):
            return self._render_multi_enum_input(streamlit_app, key, property)

        if schema_utils.is_single_file_property(property):
            return self._render_single_file_input(streamlit_app, key, property)

        if schema_utils.is_multi_file_property(property):
            return self._render_multi_file_input(streamlit_app, key, property)

        if schema_utils.is_single_datetime_property(property):
            return self._render_single_datetime_input(streamlit_app, key, property)

        if schema_utils.is_single_boolean_property(property):
            return self._render_single_boolean_input(streamlit_app, key, property)

        if schema_utils.is_single_dict_property(property):
            return self._render_single_dict_input(streamlit_app, key, property)

        if schema_utils.is_single_number_property(property):
            return self._render_single_number_input(streamlit_app, key, property)

        if schema_utils.is_single_string_property(property):
            return self._render_single_string_input(streamlit_app, key, property)

        if schema_utils.is_single_object(property, self._schema_references):
            return self._render_single_object_input(streamlit_app, key, property)

        if schema_utils.is_object_list_property(property, self._schema_references):
            return self._render_object_list_input(streamlit_app, key, property)

        if schema_utils.is_property_list(property):
            return self._render_property_list_input(streamlit_app, key, property)

        if schema_utils.is_single_reference(property):
            return self._render_single_reference(streamlit_app, key, property)

        streamlit_app.warning(
            "The type of the following property is currently not supported: "
            + str(property.get("title"))
        )
        raise Exception("Unsupported property")


class OutputUI:
    def __init__(self, output_data: Any, input_data: Any):
        self._output_data = output_data
        self._input_data = input_data

    def render_ui(self) -> None:
        try:
            if isinstance(self._output_data, BaseModel):
                self._render_single_output(st, self._output_data)
                return
            if type(self._output_data) == list:
                self._render_list_output(st, self._output_data)
                return
        except Exception as ex:
            st.exception(ex)
            # Fallback to
            st.json(jsonable_encoder(self._output_data))

    def _render_single_text_property(
        self, streamlit: st, property_schema: Dict, value: Any
    ) -> None:
        # Add title and subheader
        streamlit.subheader(property_schema.get("title"))
        if property_schema.get("description"):
            streamlit.markdown(property_schema.get("description"))
        if value is None or value == "":
            streamlit.info("No value returned!")
        else:
            streamlit.code(str(value), language="plain")

    def _render_single_file_property(
        self, streamlit: st, property_schema: Dict, value: Any
    ) -> None:
        # Add title and subheader
        streamlit.subheader(property_schema.get("title"))
        if property_schema.get("description"):
            streamlit.markdown(property_schema.get("description"))
        if value is None or value == "":
            streamlit.info("No value returned!")
        else:
            # TODO: Detect if it is a FileContent instance
            # TODO: detect if it is base64
            file_extension = ""
            if "mime_type" in property_schema:
                mime_type = property_schema["mime_type"]
                file_extension = mimetypes.guess_extension(mime_type) or ""

                if is_compatible_audio(mime_type):
                    streamlit.audio(value.as_bytes(), format=mime_type)
                    return

                if is_compatible_image(mime_type):
                    streamlit.image(value.as_bytes())
                    return

                if is_compatible_video(mime_type):
                    streamlit.video(value.as_bytes(), format=mime_type)
                    return

            filename = (
                (property_schema["title"] + file_extension)
                .lower()
                .strip()
                .replace(" ", "-")
            )
            streamlit.markdown(
                f'<a href="data:application/octet-stream;base64,{value}" download="{filename}"><input type="button" value="Download File"></a>',
                unsafe_allow_html=True,
            )

    def _render_single_complex_property(
        self, streamlit: st, property_schema: Dict, value: Any
    ) -> None:
        # Add title and subheader
        streamlit.subheader(property_schema.get("title"))
        if property_schema.get("description"):
            streamlit.markdown(property_schema.get("description"))

        streamlit.json(jsonable_encoder(value))

    def _render_single_output(self, streamlit: st, output_data: BaseModel) -> None:
        try:
            if has_output_ui_renderer(output_data):
                if function_has_named_arg(output_data.render_output_ui, "input"):  # type: ignore
                    # render method also requests the input data
                    output_data.render_output_ui(streamlit, input=self._input_data)  # type: ignore
                else:
                    output_data.render_output_ui(streamlit)  # type: ignore
                return
        except Exception:
            # Use default auto-generation methods if the custom rendering throws an exception
            logger.exception(
                "Failed to execute custom render_output_ui function. Using auto-generation instead"
            )

        model_schema = output_data.schema(by_alias=False)
        model_properties = model_schema.get("properties")
        definitions = model_schema.get("definitions")

        if model_properties:
            for property_key in output_data.__dict__:
                property_schema = model_properties.get(property_key)
                if not property_schema.get("title"):
                    # Set property key as fallback title
                    property_schema["title"] = property_key

                output_property_value = output_data.__dict__[property_key]

                if has_output_ui_renderer(output_property_value):
                    output_property_value.render_output_ui(streamlit)  # type: ignore
                    continue

                if isinstance(output_property_value, BaseModel):
                    # Render output recursivly
                    streamlit.subheader(property_schema.get("title"))
                    if property_schema.get("description"):
                        streamlit.markdown(property_schema.get("description"))
                    self._render_single_output(streamlit, output_property_value)
                    continue

                if property_schema:
                    if schema_utils.is_single_file_property(property_schema):
                        self._render_single_file_property(
                            streamlit, property_schema, output_property_value
                        )
                        continue

                    if (
                        schema_utils.is_single_string_property(property_schema)
                        or schema_utils.is_single_number_property(property_schema)
                        or schema_utils.is_single_datetime_property(property_schema)
                        or schema_utils.is_single_boolean_property(property_schema)
                    ):
                        self._render_single_text_property(
                            streamlit, property_schema, output_property_value
                        )
                        continue
                    if definitions and schema_utils.is_single_enum_property(
                        property_schema, definitions
                    ):
                        self._render_single_text_property(
                            streamlit, property_schema, output_property_value.value
                        )
                        continue

                    # TODO: render dict as table

                    self._render_single_complex_property(
                        streamlit, property_schema, output_property_value
                    )
            return

        # Display single field in code block:
        # if len(output_data.__dict__) == 1:
        #     value = next(iter(output_data.__dict__.values()))

        #     if type(value) in (int, float, str):
        #         # Should not be a complex object (with __dict__) -> should be a primitive
        #         # hasattr(output_data.__dict__[0], '__dict__')
        #         streamlit.subheader("This is a test:")
        #         streamlit.code(value, language="plain")
        #         return

        # Fallback to json output
        streamlit.json(jsonable_encoder(output_data))

    def _render_list_output(self, streamlit: st, output_data: List) -> None:
        try:
            data_items: List = []
            for data_item in output_data:
                if has_output_ui_renderer(data_item):
                    # Render using the render function
                    data_item.render_output_ui(streamlit)  # type: ignore
                    continue
                data_items.append(data_item.dict())
            # Try to show as dataframe
            streamlit.table(pd.DataFrame(data_items))
        except Exception:
            # Fallback to
            streamlit.json(jsonable_encoder(output_data))


def render_streamlit_ui(opyrator: Opyrator) -> None:
    session_state = streamlit_utils.get_session_state()

    title = opyrator.name
    if "opyrator" not in opyrator.name.lower():
        title += " - Opyrator"

    # Page config can only be setup once
    # st.set_page_config(page_title="Opyrator", page_icon=":arrow_forward:")

    st.title(title)

    # Add custom css settings
    st.markdown(f"<style>{CUSTOM_STREAMLIT_CSS}</style>", unsafe_allow_html=True)

    if opyrator.description:
        st.markdown(opyrator.description)

    InputUI(session_state=session_state, input_class=opyrator.input_type).render_ui()

    st.markdown("---")

    clear_col, execute_col = st.beta_columns([1, 2])

    with clear_col:
        if st.button("Clear"):
            # Clear all state
            session_state.clear()
            st.experimental_rerun()

    with execute_col:
        execute_selected = st.button("Execute")

    if execute_selected:
        with st.spinner("Executing operation. Please wait..."):
            try:
                input_data_obj = parse_obj_as(
                    opyrator.input_type, session_state.input_data
                )
                session_state.output_data = opyrator(input=input_data_obj)
                session_state.latest_operation_input = input_data_obj  # should this really be saved as additional session object?
            except ValidationError as ex:
                st.error(ex)
            else:
                # st.success("Operation executed successfully.")
                pass

    if session_state.output_data:
        OutputUI(
            session_state.output_data, session_state.latest_operation_input
        ).render_ui()

        st.markdown("---")

        show_json = st.empty()
        # with st.beta_expander(label="Show JSON Output", expanded=False):
        if show_json.button("Show JSON Output"):
            # Shows json if button is selected
            show_json.json(session_state.output_data.json())
